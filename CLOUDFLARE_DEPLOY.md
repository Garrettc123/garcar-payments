# Cloudflare Workers + D1 — Master Launch Path

**This is the final production surface for garcar-payments.**

Railway is fully bypassed. The edge stack is:

- Optimized Python Worker (`app/entry.py`)
- Durable Stripe Queue
- D1 (edge SQLite) for events, jobs, entitlements
- Lazy FastAPI for business routes
- AutoKey for secrets + products + webhook

---

## One-time setup (run once)

```bash
# 1. Create the D1 database
npx wrangler d1 create garcar-payments-db
# → copy the database_id into wrangler.toml

# 2. Apply schema
npx wrangler d1 execute garcar-payments-db --file=migrations/0001_d1_init.sql

# 3. Create queues (if not already present)
npx wrangler queues create stripe-events
npx wrangler queues create stripe-events-dlq
```

---

## Deploy

```bash
gh workflow run deploy-cloudflare.yml --repo Garrettc123/garcar-payments --ref main
```

Or:

```bash
npx wrangler deploy --name garcar-payments
```

---

## Bootstrap secrets + Stripe objects

```bash
export STRIPE_SECRET_KEY=sk_live_...
export CLOUDFLARE_API_TOKEN=...
export APP_BASE_URL=https://garcar-payments.<subdomain>.workers.dev

python scripts/autokey_bootstrap_cf.py
```

---

## Verification

```bash
URL=https://garcar-payments.<subdomain>.workers.dev

curl -s $URL/health | jq
# expect: "edge": true, low ms, optional d1 stats on /readyz

curl -s $URL/readyz | jq

curl -s -X POST $URL/create-checkout-session \
  -H 'Content-Type: application/json' \
  -d '{"plan":"audit","email":"launch@garcar.com","source":"master-launch"}' | jq
```

---

## Architecture (final)

```
Stripe
  │
  ▼
/stripe-webhook  ──►  STRIPE_QUEUE  ──►  queue() consumer
                                              │
                                              ▼
                                         D1 (billing_events
                                              fulfillment_jobs
                                              download_entitlements)

Business routes (checkout, download, pricing)
  │
  ▼
lazy FastAPI (app.main) when needed
```

Health endpoints never touch D1 or FastAPI → true edge performance.

---

## Dual-backend note

- **Edge (Workers)** → `app/d1.py`
- **Local / container** → `app/db.py` (SQLAlchemy)

Both share the same logical schema. The Worker path is authoritative for production traffic.
