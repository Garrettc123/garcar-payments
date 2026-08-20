# garcar-payments

FastAPI service for Garcar Enterprise payments (Stripe Checkout + webhooks, fulfillment, signed download links).

**Primary production target: Cloudflare Workers**  
Railway is optional / fallback only.

See **[CLOUDFLARE_DEPLOY.md](./CLOUDFLARE_DEPLOY.md)** for the launch path.

---

## Setup checklist

### Required secrets (GitHub → Settings → Secrets → Actions)

- [ ] `CLOUDFLARE_API_TOKEN` — Cloudflare Workers token
- [ ] `STRIPE_SECRET_KEY` — Stripe live secret key
- [ ] `STRIPE_WEBHOOK_SECRET` — Set by AutoKey or manually after webhook creation
- [ ] `STRIPE_PRICE_AUDIT` / `DEALDESK` / `STARTER` / `PRO` / `AGENCY` — or let AutoKey create them
- [ ] `APP_BASE_URL` — Public Worker URL (no trailing slash)
- [ ] `DOWNLOAD_SIGNING_SECRET` — `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] `RESEND_API_KEY` + `EMAIL_FROM` — for post-purchase email

### Optional

- [ ] `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- [ ] `CORS_ALLOW_ORIGINS`
- [ ] `LINEAR_API_KEY`, `NOTION_TOKEN`, etc.

### One-time external steps

- [ ] Deploy Worker (`gh workflow run deploy-cloudflare.yml`)
- [ ] Run `python scripts/autokey_bootstrap_cf.py` (creates prices, queues, webhook, secrets)
- [ ] Confirm `/health` returns `"edge": true`

---

## Local development

```sh
cp .env.example .env
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

## Tests

```sh
pip install -r requirements-dev.txt pydantic-settings resend itsdangerous
pytest tests/ -v
```

## API overview

| Method | Path                       | Purpose                        |
|--------|----------------------------|--------------------------------|
| GET    | `/livez`                   | Liveness                       |
| GET    | `/readyz`                  | Readiness                      |
| GET    | `/health`                  | Edge + offer status            |
| GET    | `/pricing`                 | Public pricing                 |
| POST   | `/create-checkout-session` | Stripe Checkout                |
| POST   | `/stripe-webhook`          | Stripe events (queued on edge) |
| GET    | `/download`                | Signed download                |
| GET    | `/success`                 | Post-payment page              |
| GET    | `/mrr`                     | MRR summary                    |

---

## Architecture (Cloudflare)

```
Stripe ──► /stripe-webhook ──► STRIPE_QUEUE (durable)
                                    │
                            Worker queue consumer
                                    │
                            Fulfillment + entitlement + email
```

See [CLOUDFLARE_DEPLOY.md](./CLOUDFLARE_DEPLOY.md) for full launch instructions.  
See [AUTOKEY.md](./AUTOKEY.md) for secret propagation design.  
See [RUNBOOK.md](./RUNBOOK.md) for operational procedures.
