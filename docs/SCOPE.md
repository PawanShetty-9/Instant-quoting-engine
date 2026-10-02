# Product scope – Instant Quoting Engine v1.0

## 1. Problem

A German CNC job shop (*Lohnfertiger*, 20–250 employees) receives dozens of requests for
quotation (RFQs) per week. Each one needs an estimator (*Kalkulator*) to open the CAD model, plan
the operations, estimate times and write a quote. That takes 30 minutes to several hours per part,
and customers wait 2–5 days. Online platforms (Xometry, Protolabs, Facturee) have taught buyers to
expect a price **in seconds**. Shops that answer late lose the order before their quote arrives.

## 2. Product

A self-hosted micro-service plus portal. The customer uploads a 3D model (STEP) and within seconds
receives:

- the selected manufacturing process (3-axis milling, 5-axis milling or turning), from rule-based
  feature recognition
- production time, lead time (against the **live** machine availability and backlog) and price
- a legally sound, bilingual (DE/EN) quote with 19 % VAT, printable as a DIN 5008 letter

The shop keeps control. Its own machine rates, material prices, margins and capacities drive every
number. Anything unusual is routed to a human as *Review Required*.

## 3. Users

| Persona | Goal | Touchpoint |
|---|---|---|
| Buyer / design engineer (customer) | Price and delivery date now, without a sales call | Portal: upload → quote → print/PDF |
| Sales back office (*Innendienst*) | Convert RFQs, only handle exceptions | Quote ID lookup, *Review Required* queue (roadmap) |
| Estimator / production planner (*Kalkulator / AV*) | Trust the numbers | Cost model, calibration, per-quote analysis block |
| Plant manager / MES | Feed real capacity into quoting | `PUT /api/v1/factory` (e.g. from the Industrie 4.0 telemetry gateway) |
| ERP / IT | Use the engine from existing systems | `POST /api/v1/engine/evaluate` (API key) |

## 4. Goals & success metrics

| Metric | Target v1.0 |
|---|---|
| Time to quote, STEP ≤ 10 MB (p95) | < 10 s rules-only, < 45 s with AI review |
| Quote accuracy after calibration | ≥ 80 % of parts within ±15 % of the estimator's manual quote |
| Share of quotes needing no manual touch | ≥ 60 % *Feasible* |
| Arithmetic correctness | 100 % (cent-exact, enforced by tests) |
| Availability | 99.5 % monthly (single node + health checks + auto-restart) |

## 5. In scope (v1.0 – delivered)

1. **CAD ingestion:** STEP AP203/214/242 (primary), IGES, STL (mesh, always *Review Required*).
   Parsing runs in a sandboxed subprocess with timeout and memory/CPU limits, and files are
   content-sniffed.
2. **Geometry analysis (OpenCascade):** volume, area, tight bounding box, holes, tap-drill threads,
   pockets/steps, free-form clusters, turnability, access directions, inclined features,
   smallest hole and internal radius, hole L/D.
3. **Machine selection** per the engine contract (rule 1), with envelope checks and fallback.
4. **Time & cost model** per rules 2–3, extended with batch quantities and multiple set-ups.
5. **German compliance** (rule 4): 19 % MwSt, gross price, bilingual notes, standard terms
   (freibleibend, ISO 2768-mK, EN 10204 2.2, FCA Incoterms 2020, § 377 HGB, GDPR, GeschGehG), and a
   DIN 5008 letter with the § 35a GmbHG company details.
6. **Claude review layer:** structured output in the exact contract schema, server-side refusal
   fallback, prompt caching and a deterministic reconciliation guardrail. Service-computed numbers
   always win.
7. **Portal (Next.js):** upload, material and quantity, thread override, 3D preview, title-block
   quote sheet, cost composition, printable quote, sample parts.
8. **Integration API:** raw engine endpoint and factory state (availability, backlog, rates, material
   prices) behind an API key.
9. **Operations:** Docker images (non-root, read-only rootfs, health checks), Compose stack with
   automatic HTTPS (Caddy), Render blueprint, GitHub Actions CI, GHCR release images, SQLite audit
   trail with retention purge.

## 6. Out of scope (v1.0)

- Processes other than CNC milling and turning: sheet metal, additive, casting, EDM, grinding
- Reading 2D drawings (PDF/TIFF): tolerances, GD&T, surface callouts, thread specifications
- Surface treatment, heat treatment, coatings, assembly, special packaging
- Customer accounts, order placement / e-signature, payment, ERP order transfer
- Multi-currency, customer-specific price lists, framework contracts / call-offs
- Horizontal scaling across several nodes (SQLite and the rate limiter are single-node by design)

## 7. Assumptions & constraints

- Customer uploads are solid models in millimetres (STEP carries units; STL units are selected in
  the UI).
- The shop provides its real hourly rates, material prices and margin before go-live
  ([COST_MODEL.md](COST_MODEL.md) §2–3), and calibrates against historical quotes.
- An automated quote is **non-binding** (*freibleibend*). A contract needs the shop's written order
  confirmation, which covers the risk of misrecognised features.
- CAD files are trade secrets. Only derived numeric metadata may leave the service (to Anthropic,
  and only if AI is enabled).

## 8. Non-functional requirements

| Area | Requirement → implementation |
|---|---|
| Security | Upload size cap (413), extension + magic-byte check, isolated parser process (timeout, `RLIMIT_AS`, `RLIMIT_CPU`), API-key auth with constant-time compare, per-IP rate limit, strict security headers / CSP, non-root read-only containers, no stack traces to clients |
| Privacy (DSGVO) | No CAD file, filename or customer reference is sent to the AI; retention purge (default 90 days); self-hosted fonts (no Google Fonts requests); EU hosting region in the blueprint |
| Correctness | `Decimal` money, cent-exact identities, reconciliation of AI output, 84 automated tests |
| Robustness | AI failure, refusal, timeout or misconfiguration → deterministic rules quote (or 503 in `required` mode) |
| Auditability | Every quote stored with engine input, flags, candidates, AI model and validation log |
| Maintainability | Typed Pydantic contracts, ruff lint/format, CI on every push |

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| LLM invents prices or times | Claude chooses among pre-computed candidates only; guardrail re-derives all figures; deviations logged |
| Feature misrecognition (e.g. cosmetic threads) | Flags + UI override + *Review Required* + freibleibend terms |
| Cost model drifts from reality | Factory API for live rates/prices; calibration procedure; analysis block for estimators |
| Malicious CAD files (parser DoS) | Sandbox process, limits, concurrency semaphore, rate limit |
| Legal exposure of automated offers | Freibleibend clause, stated assumptions, template marked for legal review |

## 10. Roadmap

| Version | Content |
|---|---|
| 1.1 | Drawing (PDF) ingestion with Claude vision: tolerances, threads, surface callouts → price adders |
| 1.2 | *Review Required* inbox for the back office; e-mail notifications; quote → order acceptance |
| 1.3 | Automatic calibration: regression of MRR, penalties and rates on historical quotes |
| 1.4 | ERP connectors (SAP Business One, abas, proAlpha); MES push via the Industrie 4.0 telemetry gateway (OPC UA machine states → availability) |
| 2.0 | Further processes (turn-mill, sheet metal); thin-wall and tool-reach analysis; PostgreSQL + Redis for multi-node |

## 11. Acceptance criteria v1.0 (all automated in `backend/tests`)

- The four reference parts route to 3-axis / lathe / 5-axis (multi-sided) / 5-axis (free-form).
- The hand-calculated contract example is reproduced to the cent; `net + VAT = gross` holds for
  every quantity.
- An unavailable machine re-routes to a free capable machine; without one it yields `Capacity Delay` and +5 days.
- Oversized parts are *Infeasible*; envelope re-routing and high order values are *Review Required*.
- AI output with wrong numbers is corrected; AI cannot downgrade a hard-rule severity; refusals and
  API errors fall back to rules.
- No file name or customer reference reaches the AI payload.
- Upload limits (413), wrong/forged file types (422), rate limits (429) and API-key protection
  (401/503) behave as specified.
