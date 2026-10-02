# Deployment

Three supported paths. All of them run the same two images:

| Image | Base | Notes |
|---|---|---|
| `backend` | `python:3.12-slim-bookworm` | non-root (uid 10001), OpenCascade 8 + VTK (≈ 2 GB), health check, `/data` volume |
| `frontend` | `node:22-alpine` | Next.js standalone server, non-root, ≈ 330 MB |

Every push to `main` and every `v*` tag publishes both images to GHCR
(`ghcr.io/<owner>/<repo>-backend`, `-frontend`) via `.github/workflows/release.yml`.

---

## A. Single server / on-premises (recommended for Mittelstand)

A VM or server in the plant DMZ (Linux, Docker 24+, 2 vCPU, 4 GB RAM, 20 GB disk) and a DNS name.

```bash
git clone https://github.com/<owner>/instant-quoting-engine.git && cd instant-quoting-engine
cp .env.example .env
#   SITE_ADDRESS=angebot.musterfertigung.de
#   QUOTE_CORS_ORIGINS=["https://angebot.musterfertigung.de"]
#   QUOTE_ADMIN_API_KEY=$(openssl rand -hex 32)
#   ANTHROPIC_API_KEY=sk-ant-...        (optional)
#   QUOTE_COMPANY_* = your legal entity data (printed on every quote)
docker compose up -d --build
```

Caddy obtains a Let's Encrypt certificate automatically (ports 80/443 must be reachable). For an
intranet-only test use `SITE_ADDRESS=:80`.

**Hardening built into `docker-compose.yml`:** read-only root filesystems, `tmpfs` for `/tmp`,
`no-new-privileges`, all capabilities dropped, a memory limit for the backend, and the backend only
reachable through Caddy.

**Behind a TLS-inspecting corporate proxy** (common on plant networks), pass your CA as a build
secret. It is used for `apt`, `pip` and `npm` and never stored in an image layer:

```bash
docker build --secret id=corp_ca,src=/etc/ssl/certs/corp-ca.pem -t quote-backend backend/
docker build --secret id=corp_ca,src=/etc/ssl/certs/corp-ca.pem -t quote-frontend frontend/
```

**Backups:** the only state is the `quote-data` volume (SQLite, WAL mode):

```bash
docker compose exec backend python -c "import sqlite3; s=sqlite3.connect('/data/quotes.sqlite3'); d=sqlite3.connect('/data/backup.sqlite3'); s.backup(d)"
docker compose cp backend:/data/backup.sqlite3 ./backup-$(date +%F).sqlite3
```

**Updates:** `git pull && docker compose up -d --build` (or pin `IMAGE_TAG` to a GHCR release and
`docker compose pull`).

## B. Render (managed, EU region)

1. Push the repository to GitHub.
2. In Render choose **New → Blueprint** and select the repository; `render.yaml` creates
   `quote-backend` (Docker, Frankfurt, 5 GB persistent disk, generated admin key) and
   `quote-frontend`.
3. Set `ANTHROPIC_API_KEY` on `quote-backend` (optional).
4. If you rename services or add a custom domain, update `QUOTE_CORS_ORIGINS` (backend) and
   `NEXT_PUBLIC_API_BASE_URL` (frontend; it is inlined at build time, so redeploy the frontend).

## C. Vercel (frontend) + any container host (backend)

- Frontend: import `frontend/` into Vercel and set `NEXT_PUBLIC_API_BASE_URL=https://api.example.de`.
- Backend: run the backend image on Fly.io, Azure Container Apps, AWS App Runner/ECS or Kubernetes
  with ≥ 2 GB RAM, a persistent volume at `/data`,
  `QUOTE_CORS_ORIGINS=["https://<your-vercel-domain>"]` and `FORWARDED_ALLOW_IPS` set to your
  ingress CIDR.

---

## Configuration reference

All backend settings are environment variables with the prefix `QUOTE_` (see
[`backend/app/config.py`](../backend/app/config.py) and [`.env.example`](../.env.example)).

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Enables the Claude review layer |
| `QUOTE_AI_MODE` | `auto` | `auto` (AI if key, else rules) · `off` · `required` (503 if AI fails) |
| `QUOTE_ANTHROPIC_MODEL` | `claude-opus-5` | Model ID |
| `QUOTE_ANTHROPIC_EFFORT` | `medium` | `low`…`max`; higher = deeper review, slower |
| `QUOTE_ADMIN_API_KEY` | – | Enables `/engine/evaluate` and `/factory` |
| `QUOTE_CORS_ORIGINS` | `["http://localhost:3000"]` | JSON list of allowed browser origins |
| `QUOTE_MAX_UPLOAD_MB` | 25 | Upload cap |
| `QUOTE_PARSE_TIMEOUT_S` / `_MEMORY_LIMIT_MB` | 45 / 2048 | Sandbox limits per CAD file |
| `QUOTE_RATE_LIMIT_PER_WINDOW` / `_WINDOW_S` | 20 / 600 | Quotes per IP per window |
| `QUOTE_RATE_CNC_3_AXIS_EUR_H` … | 85 / 110 / 75 | Default hourly rates |
| `QUOTE_DEFAULT_ENERGY_SURCHARGE_PERCENT` | 4 | Energy surcharge |
| `QUOTE_DEFAULT_TARGET_MARGIN_PERCENT` | 15 | Margin |
| `QUOTE_MATERIAL_BASIS` | `stock` | `stock` (raw blank) or `part` (original contract formula) |
| `QUOTE_MARGIN_MODE` | `markup` | `markup` (Gewinnzuschlag) or `margin` |
| `QUOTE_QUOTE_VALIDITY_DAYS` | 30 | Price validity printed on the quote |
| `QUOTE_QUOTE_RETENTION_DAYS` | 90 | Deletion period for stored quotes |
| `QUOTE_HIGH_VALUE_REVIEW_THRESHOLD_EUR` | 25000 | Net value that triggers commercial review |
| `QUOTE_COMPANY_*` | placeholders | Legal entity data (§ 35a GmbHG) on every quote |
| `WEB_CONCURRENCY` | 2 | Uvicorn workers |
| `FORWARDED_ALLOW_IPS` | 127.0.0.1 | Proxies trusted for `X-Forwarded-For` |
| `QUOTE_TRUSTED_PROXY_HOPS` | 0 | Reverse proxies in front of the API (Caddy/Render: 1); the client IP for quotas is read from that position in `X-Forwarded-For` |
| `QUOTE_PUBLIC_APP_URL` | `http://localhost:3000` | Web app URL; Stripe redirects back here |
| `QUOTE_STRIPE_SECRET_KEY` | – | `sk_test_…` first, `sk_live_…` at launch. Unset: demo upgrades outside production, checkout disabled in production |
| `QUOTE_STRIPE_WEBHOOK_SECRET` | – | `whsec_…` of the endpoint `/api/v1/billing/webhook` (events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`) |
| `QUOTE_STRIPE_AUTOMATIC_TAX` | false | Let Stripe Tax add 19 % MwSt to subscription invoices |
| `QUOTE_BILLING_DEMO_MODE` | true | Allow keyless demo upgrades (never in production) |

## Payments (Stripe)

Plans, prices, quotas and features are defined once in `backend/app/billing/plans.py`; the pricing
page and Stripe Checkout read from there. To try the paid flow end to end in **test mode**:

1. Create a Stripe account and copy the test secret key (`sk_test_…`) into `QUOTE_STRIPE_SECRET_KEY`.
2. Forward webhooks locally: `stripe listen --forward-to localhost:8000/api/v1/billing/webhook`
   and put the printed `whsec_…` into `QUOTE_STRIPE_WEBHOOK_SECRET`.
3. Sign up in the web app, choose Pro, pay with card `4242 4242 4242 4242`. The webhook switches
   the account to Pro; cancelling in the customer portal switches it back to Free.

No products or prices need to be created in Stripe: Checkout receives the price from `plans.py`.

## Go-live checklist

- [ ] Stripe live keys and webhook set, Stripe Tax (or tax rates) activated, customer portal
      configured to allow cancellation

- [ ] Real company data in `QUOTE_COMPANY_*`; terms in `backend/app/legal/terms.py` reviewed by
      counsel and aligned with your AGB
- [ ] Hourly rates, material prices, margin and energy surcharge set; calibration against
      historical quotes done ([COST_MODEL.md](COST_MODEL.md))
- [ ] `QUOTE_ADMIN_API_KEY` generated; MES/ERP pushing availability and backlog
- [ ] If AI is enabled: Anthropic listed as processor in your *Verzeichnis von
      Verarbeitungstätigkeiten* (a DPA is available from Anthropic)
- [ ] Backups of the `quote-data` volume scheduled
- [ ] Privacy notice (*Datenschutzerklärung*) and legal notice (*Impressum*) linked from your
      website
