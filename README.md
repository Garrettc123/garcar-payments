# garcar-payments

FastAPI service for Garcar Enterprise payments with Stripe Checkout, verified webhooks, durable fulfillment, Supabase entitlements, CRM onboarding, audit logging, and incident creation.

## End-to-end checkout flow

```text
Stripe checkout.session.completed
  -> durable BillingEvent + FulfillmentJob
  -> Stripe payment/customer verification
  -> HubSpot contact match + Stripe customer link
  -> Supabase garcar_entitlements upsert
  -> Asana onboarding project + task
  -> Notion audit event
  -> existing download entitlement + email
  -> COMPLETED

Any failed stage
  -> durable stage failure
  -> retry with exponential backoff
  -> Linear incident
  -> dead-letter after MAX_ATTEMPTS
```

Every checkout is correlated by the immutable Stripe event ID. Fulfillment jobs and integration stages are idempotent at the database layer so Stripe retries do not create duplicate logical entitlements.

## Production integration secrets

Required for the full orchestration path:

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `HUBSPOT_ACCESS_TOKEN`
- `ASANA_ACCESS_TOKEN`
- `ASANA_WORKSPACE_GID`
- `NOTION_TOKEN`
- `NOTION_REVENUE_DB_ID`
- `LINEAR_API_KEY`
- `LINEAR_TEAM_ID`

See `.env.example` for the complete environment contract. Secrets are not committed to the repository.

## Database

Run the application migration before production traffic:

```sh
alembic upgrade head
```

Apply `supabase/migrations/20260818000000_garcar_entitlements.sql` to the Supabase project before enabling entitlement provisioning.

## Running locally

```sh
cp .env.example .env
pip install -r requirements-dev.txt
python -m app.supervisor
```

The supervisor runs FastAPI and the durable checkout worker together. The worker claims pending jobs atomically and resumes completed stages rather than restarting the whole workflow.

## Running tests

```sh
pip install -r requirements-dev.txt pydantic-settings resend itsdangerous bandit
pytest tests/ -v
```

## Docker

```sh
docker build -t garcar-payments .
docker run -p 8000:8000 --env-file .env garcar-payments
```

## API

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
| GET | `/mrr` | MRR summary |

## Cloudflare

Cloudflare Workers sends Stripe webhook requests to the `stripe-events` durable queue. The queue consumer verifies the Stripe signature, persists the event/job, and executes the same end-to-end orchestration. Queue retries are backed by `stripe-events-dlq`.

See `AUTOKEY.md` and `RUNBOOK.md` for deployment and operational procedures.
