# garcar-payments

FastAPI service for Garcar Enterprise payments (Stripe Checkout + webhooks,
fulfillment, signed download links).

## Setup checklist

### Required secrets (set in GitHub → Settings → Secrets → Actions)

- [ ] `STRIPE_SECRET_KEY` — Stripe live secret key
- [ ] `STRIPE_WEBHOOK_SECRET` — From Stripe webhook dashboard
- [ ] `STRIPE_PRICE_AUDIT` — Stripe Price ID for Operational Audit
- [ ] `STRIPE_PRICE_DEALDESK` — Stripe Price ID for AI Deal Desk Setup
- [ ] `STRIPE_PRICE_STARTER` — Stripe Price ID for Starter Subscription
- [ ] `STRIPE_PRICE_PRO` — Stripe Price ID for Pro Subscription
- [ ] `STRIPE_PRICE_AGENCY` — Stripe Price ID for Agency Subscription
- [ ] `APP_BASE_URL` — Public service URL (no trailing slash)
- [ ] `DATABASE_URL` — PostgreSQL connection string
- [ ] `DOWNLOAD_SIGNING_SECRET` — Random 32-byte hex; generate with `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] `RESEND_API_KEY` — Resend transactional email API key
- [ ] `EMAIL_FROM` — Sender address (e.g. `noreply@garcar.com`)
- [ ] `RAILWAY_TOKEN` — Railway service deploy token (not account-wide)
- [ ] `BACKUP_ENCRYPTION_KEY` — Passphrase for AES backup encryption

### Optional secrets

- [ ] `SUPABASE_URL` — Supabase project URL
- [ ] `SUPABASE_SERVICE_KEY` — Supabase service role key
- [ ] `CORS_ALLOW_ORIGINS` — Comma-separated allowed origins (default `*`)
- [ ] `LINEAR_API_KEY`, `LINEAR_TEAM_ID` — Linear integration
- [ ] `NOTION_TOKEN`, `NOTION_REVENUE_DB_ID` — Notion integration

### One-time external setup (human steps)

> These cannot be automated without credentials.

- [ ] Create a `production` GitHub Environment at Settings → Environments → New environment.
      Add required reviewers so every production deploy requires approval.
- [ ] Create the Stripe webhook endpoint pointing to `$APP_BASE_URL/stripe-webhook`
      with events: `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`,
      `customer.subscription.created/updated/deleted`, `payment_intent.succeeded`.
- [ ] Set up Railway service and copy `RAILWAY_TOKEN` into GitHub Secrets.
- [ ] Provision a PostgreSQL database (Railway Postgres add-on or Supabase) and set `DATABASE_URL`.
- [ ] Configure Resend account and verify sender domain.

### Running locally

```sh
cp .env.example .env
# Fill in .env with real values
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

### Running tests

```sh
pip install -r requirements-dev.txt pydantic-settings resend itsdangerous
pytest tests/ -v
```

### Running database migrations

```sh
alembic upgrade head
```

### Docker

```sh
docker build -t garcar-payments .
docker run -p 8000:8000 --env-file .env garcar-payments
```

## API overview

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/livez` | Liveness probe |
| GET | `/readyz` | Readiness probe |
| GET | `/health` | Offer catalog status |
| GET | `/pricing` | Public pricing |
| POST | `/create-checkout-session` | Create Stripe Checkout session |
| POST | `/stripe-webhook` | Receive Stripe events |
| GET | `/download` | Serve signed download link |
| GET | `/success` | Post-payment success page |
| GET | `/mrr` | MRR summary (requires Supabase) |

## Architecture

```
Stripe ──► /stripe-webhook ──► BillingEvent (idempotent)
                            ──► FulfillmentJob (pending)
                                    │
                            worker.run_pending()
                                    │
                            DownloadEntitlement + email
```

See [AUTOKEY.md](./AUTOKEY.md) for OIDC/keyless authentication design.
See [RUNBOOK.md](./RUNBOOK.md) for operational procedures.
