# garcar-payments

Garcar Enterprise payment control plane: Stripe Checkout, signed webhooks, durable fulfillment, Supabase entitlements, CRM/onboarding integrations, audit logging, signed downloads, and retry/dead-letter handling.

## Checkout orchestration

```text
Stripe Checkout
  -> verified Stripe webhook
  -> durable queue
  -> idempotent BillingEvent + FulfillmentJob
  -> Stripe payment/customer verification
  -> HubSpot contact match/link
  -> Supabase entitlement upsert
  -> Asana onboarding
  -> Notion audit event
  -> download entitlement + email
  -> COMPLETED

Failure -> durable stage state -> exponential retry -> Linear incident -> DEAD after max attempts
```

The immutable Stripe event ID and Checkout Session ID are the correlation keys. Per-stage state, unique constraints, provider operation keys, and reconciliation prevent duplicate logical side effects.

## Production requirements

Required: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, all five `STRIPE_PRICE_*` values, `APP_BASE_URL`, `DATABASE_URL`, `DOWNLOAD_SIGNING_SECRET`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `HUBSPOT_ACCESS_TOKEN`, `ASANA_ACCESS_TOKEN`, `ASANA_WORKSPACE_GID`, `NOTION_TOKEN`, `NOTION_REVENUE_DB_ID`, `LINEAR_API_KEY`, `LINEAR_TEAM_ID`, `RESEND_API_KEY`, and `EMAIL_FROM`.

Never commit production secrets. See `.env.example`.

## Database

```sh
alembic upgrade head
```

Apply the Supabase entitlement migration before enabling production entitlement provisioning.

## Local development

```sh
cp .env.example .env
pip install -r requirements.txt
python -m app.supervisor
```

The supervisor runs the FastAPI API and durable checkout worker together.

## Tests

```sh
pytest tests/ -v
```

## Docker

```sh
docker build -t garcar-payments .
docker run -p 8000:8000 --env-file .env garcar-payments
```

The Docker image starts `python -m app.supervisor`, not a standalone API process.

## Railway

`railway.json` also starts `python -m app.supervisor`, ensuring queued fulfillment is processed alongside the API.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/livez` | Liveness |
| GET | `/readyz` | Readiness |
| GET | `/health` | Service/offer status |
| GET | `/pricing` | Pricing catalog |
| POST | `/create-checkout-session` | Stripe Checkout |
| POST | `/stripe-webhook` | Verified Stripe events |
| GET | `/download` | Signed entitlement-gated delivery |
| GET | `/mrr` | Recurring revenue summary |
| GET | `/success` | Post-payment response |

## Cloudflare

The Worker verifies the Stripe signature before admitting a webhook to `stripe-events`. The queue consumer verifies again, persists the event/job, atomically claims the job, and executes the same orchestration path. Failed queue messages use the configured DLQ.
