# Architecture

```
                  ┌──────────────────────── Caddy (TLS, HTTP/2, request-size limit) ─────────────────────────┐
 Customer ───────►│  /            ──► Frontend: Next.js 16 (portal, 3D viewer, printable DIN 5008 quote)     │
 (browser)        │  /api/*       ──► Backend:  FastAPI (Python 3.12)                                         │
                  └───────────────────────────────────────────┬──────────────────────────────────────────────┘
                                                              │
               ┌──────────────────────────────────────────────┼──────────────────────────────────────────┐
               │ FastAPI                                      ▼                                          │
               │  ┌───────────────┐   bytes   ┌──────────────────────────────┐                            │
               │  │ Upload guard  │──────────►│ CAD parser (sandbox process) │  OpenCascade (OCP):        │
               │  │ size, sniff,  │           │  forkserver + RLIMIT_AS/CPU  │  volume, area, bbox,       │
               │  │ rate limit    │◄──────────│  + hard timeout (kill)       │  holes, threads, pockets,  │
               │  └───────────────┘ metadata  └──────────────────────────────┘  free-form, turnability,   │
               │          │                                                      access directions, mesh  │
               │          ▼                                                                               │
               │  ┌──────────────────────────────┐  cad_metadata + factory_status + cost_vectors          │
               │  │ Deterministic kernel          │  → candidates for all 3 machines (time, cost, lead)   │
               │  │ rules.py · costing.py         │  → rule-1 process, feasibility flags                  │
               │  └──────────────┬───────────────┘                                                       │
               │                 │ payload (numbers only)                                                 │
               │                 ▼                                                                        │
               │  ┌──────────────────────────────┐  claude-opus-5 · structured output (EngineQuote)       │
               │  │ Claude review (optional)      │──► adaptive thinking · prompt cache · server fallback │
               │  └──────────────┬───────────────┘                                                       │
               │                 ▼                                                                        │
               │  ┌──────────────────────────────┐  numbers re-derived from kernel · feasibility ≥ flags  │
               │  │ Reconciliation guardrail      │  · capacity notice enforced · deviations logged       │
               │  └──────────────┬───────────────┘                                                       │
               │                 ▼                                                                        │
               │  SQLite (WAL): quotes (audit trail, preview mesh) · factory_state ◄── PUT /factory (MES) │
               └──────────────────────────────────────────────────────────────────────────────────────────┘
```

## Request flow: `POST /api/v1/quotes`

1. **Rate limit** per client IP (sliding window). Behind Caddy, uvicorn's `--proxy-headers`
   resolves the real IP.
2. **Upload guard:** `Content-Length` pre-check, streamed read with a hard byte cap (413), filename
   sanitised, SHA-256 recorded.
3. **Content sniffing:** STEP (`ISO-10303-21`), IGES (column-73 `S` record), STL (binary size
   formula / ASCII `solid…facet`). The extension must match the content.
4. **Sandboxed parse:** a fresh process forked from a forkserver with OCP preloaded, so starting it
   costs no import time. The worker gets `RLIMIT_AS` = current + `QUOTE_PARSE_MEMORY_LIMIT_MB` and an
   `RLIMIT_CPU` cap, and is killed after `QUOTE_PARSE_TIMEOUT_S`. A semaphore bounds concurrent
   parses. Results cross a pipe as plain data. OCCT segfaults are reported as 422, not crashes.
5. **Kernel** (`engine/`): builds a `GeometryProfile`, resolves the material (keys, Werkstoffnummer,
   trade names), costs **every** machine class, applies rule 1 plus envelope fallback, and raises
   flags such as `CAPACITY_DELAY`, `DEEP_HOLES` or `HIGH_VALUE`.
6. **Claude review** (if `ANTHROPIC_API_KEY` is set and `QUOTE_AI_MODE != off`), described below.
7. **Commercial envelope:** unit price, validity (30 days), terms DE/EN, supplier master data.
8. **Persist** the full response plus the preview mesh; return `201` with `QuoteResponse`.

## The AI layer and its guardrail

The Claude call follows the engine contract literally. Its system prompt is the specification
(rules 1–4, German compliance, the output schema), and its output is **constrained by structured
outputs to the exact `EngineQuote` schema**. What Claude *adds* is judgement:

- confirming or (with justification) overriding the machine choice among candidates that fit
- escalating feasibility for risks the rules do not capture (slenderness, material behaviour,
  feature density)
- writing professional bilingual *Prüfhinweise*

What Claude is **not trusted with** is arithmetic that ends up on a legal document. The guardrail
in `engine/quote.py`:

| Claude output | Guardrail |
|---|---|
| `selected_process` | Must be a known machine that fits the envelope; a deviation from rule 1 forces *Review Required* |
| `cost_breakdown`, hours, lead time | Replaced by the kernel values for the chosen process (logged if different by > 1 ct) |
| `feasibility` | `max(Claude, hard-rule flags)`: can escalate, never downgrade |
| `feasibility_notes` | Must be `DE: … \| EN: …`; the Capacity Delay notice is appended if missing |
| `quote_id` | Always the service-issued ID |

Failure modes (refusal, rate limit, timeout, invalid schema, misconfiguration) fall back to the
rules quote and are recorded in `analysis.validation`. In `QUOTE_AI_MODE=required` they return 503
instead.

**Model & request settings** (`ai/claude.py`):
- model `claude-opus-5` (configurable) with adaptive thinking and `effort=medium` (latency-oriented;
  raise for harder parts)
- `client.beta.messages.parse(output_format=EngineQuote)` for schema-validated output
- server-side fallbacks (`fallbacks="default"`, beta `server-side-fallback-2026-07-01`), so a
  classifier decline is re-run on a fallback model instead of failing
- the system prompt is byte-stable and marked `cache_control: ephemeral`; the payload is serialised
  with `sort_keys=True`

## Data protection

| Data | Stored | Sent to Anthropic |
|---|---|---|
| CAD file | No (temp dir, deleted after parse) | **Never** |
| Preview mesh (tessellation) | Yes, with the quote, until retention purge | Never |
| File name, customer reference | Yes (on the quote document) | **Never** |
| Numeric metadata, costs, flags | Yes | Yes (if AI enabled) |

Retention: `QUOTE_QUOTE_RETENTION_DAYS` (default 90) is purged at start-up. Quote IDs carry
50 bits of randomness and act as unguessable capability links. There is no listing endpoint.

## Module map

```
backend/app/
  main.py            app factory, middleware, lifespan (store, engine, limiter)
  config.py          all settings (env, prefix QUOTE_)
  schemas.py         engine contract (EngineInput / EngineQuote) + API envelope
  api/routes.py      HTTP endpoints
  cad/parser.py      sniffing + sandboxed subprocess
  cad/brep.py        OpenCascade feature recognition + preview tessellation
  cad/stl.py         mesh fallback
  catalog/           materials (researched data) and machine park
  engine/costing.py  rules 2–4 (Decimal, cent-exact)
  engine/rules.py    rule 1, feasibility flags, bilingual rule notes
  engine/quote.py    orchestration + reconciliation guardrail
  ai/                Claude client + system prompt
  legal/terms.py     DE/EN commercial terms
  storage.py         SQLite (quotes, factory state)
  security.py        API key, rate limiter, security headers
frontend/
  app/page.tsx               portal
  app/quotes/[id]/page.tsx   DIN 5008 printable quote (DE/EN)
  components/                UploadPanel, QuoteSheet (title block), Stamp, CostBar, PartViewer (three.js)
```

## Scaling notes

A single node handles an RFQ portal comfortably: typical parses take 0.1–2 s, and the AI review
takes 5–30 s but is I/O-bound. To scale out, move `storage.py` to PostgreSQL, the rate limiter to
Redis, and run the backend as N replicas behind the same Caddy/ingress. Nothing else is
node-local.
