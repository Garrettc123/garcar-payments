# Production Launch — Railway Deployment Steps
## garcar-payments Stripe Checkout API

## 5-Minute Deploy

### Step 1 — Create Railway service
1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select `Garrettc123/garcar-payments`
3. Confirm Railway uses the repo `Dockerfile`
4. Deploy service

### Step 2 — Set required Railway Variables

```bash
STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET
STRIPE_PRICE_AUDIT
STRIPE_PRICE_DEALDESK
STRIPE_PRICE_STARTER
STRIPE_PRICE_PRO
STRIPE_PRICE_AGENCY
APP_BASE_URL
DATABASE_URL
CORS_ALLOW_ORIGINS
```

### Step 3 — Mirror required GitHub Actions secrets
In `garcar-payments` repo → Settings → Secrets and variables → Actions, set:

```bash
RAILWAY_TOKEN
STRIPE_SECRET_KEY
STRIPE_WEBHOOK_SECRET
STRIPE_PRICE_AUDIT
STRIPE_PRICE_DEALDESK
STRIPE_PRICE_STARTER
STRIPE_PRICE_PRO
STRIPE_PRICE_AGENCY
APP_BASE_URL
DATABASE_URL
CORS_ALLOW_ORIGINS
```

### Step 4 — Register Stripe webhook endpoint
1. Stripe Dashboard → Developers → Webhooks → **Add endpoint**
2. Endpoint URL: `https://<your-railway-url>.up.railway.app/stripe-webhook`
3. Enable at least:
   - `checkout.session.completed`
   - `invoice.paid`
4. Copy signing secret (`whsec_...`) and set `STRIPE_WEBHOOK_SECRET` in Railway and GitHub Actions secrets

### Step 5 — Run launch acceptance checks
```bash
curl https://garcar-payments.up.railway.app/health
curl https://garcar-payments.up.railway.app/pricing
curl -X POST https://garcar-payments.up.railway.app/create-checkout-session \
  -H 'Content-Type: application/json' \
  -d '{"plan":"audit","email":"test@example.com","source":"production-smoke-test"}'
```

Expected:
- `/health` returns `status: ok`
- `/pricing` includes `audit` and `dealdesk`
- `/create-checkout-session` returns a `checkout_url`

## Route Reference

| Route | Purpose |
|---|---|
| `GET /health` | Railway healthcheck |
| `GET /pricing` | Public plan catalog |
| `POST /create-checkout-session` | Start Stripe Checkout |
| `POST /stripe-webhook` | Stripe webhook receiver |
