# Railway Deployment — garcar-payments

**Launch-critical service.** This is the live Stripe checkout + webhook + fulfillment surface.

---

## 1. Create / Recreate the Railway service

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select `Garrettc123/garcar-payments`
3. Confirm builder = **Dockerfile**
4. Service name: `garcar-payments`
5. Click **Deploy**

If the old service was deleted (404 "Application not found"), simply create a new one. Railway will give you a fresh `*.up.railway.app` URL.

---

## 2. Required Environment Variables (Railway → Variables)

```
# Core (required for production)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...          # from Step 4
STRIPE_PRICE_AUDIT=price_...
STRIPE_PRICE_DEALDESK=price_...
STRIPE_PRICE_STARTER=price_...
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_AGENCY=price_...
APP_BASE_URL=https://<your-service>.up.railway.app
DATABASE_URL=postgresql://...            # Railway Postgres or external
DOWNLOAD_SIGNING_SECRET=<32-byte-hex>    # python -c "import secrets; print(secrets.token_hex(32))"
ENVIRONMENT=production

# Email (required for fulfillment)
RESEND_API_KEY=re_...
EMAIL_FROM=noreply@garcar.com

# Optional but recommended
CORS_ALLOW_ORIGINS=https://garrettc123.github.io,https://garcar.io
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
```

After saving variables, Railway auto-redeploys.

---

## 3. Health Check

```bash
curl https://<your-service>.up.railway.app/livez
# Expected: {"status":"alive","uptime_s":...}

curl https://<your-service>.up.railway.app/readyz
# Expected: {"ready":true,"service":"garcar-payments"}

curl https://<your-service>.up.railway.app/health
# Expected: {"status":"ok","service":"garcar-payments","configured_offers":[...]}

curl https://<your-service>.up.railway.app/pricing
```

---

## 4. Register Stripe Webhook

1. [Stripe Dashboard → Developers → Webhooks](https://dashboard.stripe.com/webhooks) → **Add endpoint**
2. Endpoint URL (exact):
   ```
   https://<your-service>.up.railway.app/stripe-webhook
   ```
3. Select events:
   - `checkout.session.completed`
   - `invoice.paid`
   - `invoice.payment_failed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `payment_intent.succeeded`
4. Copy the **Signing secret** (`whsec_...`)
5. Paste into Railway Variables as `STRIPE_WEBHOOK_SECRET`
6. Railway redeploys automatically

---

## 5. GitHub Secrets (for CI deploy workflow)

Repo → Settings → Secrets and variables → Actions:

```
RAILWAY_TOKEN          # Railway → Account Settings → Tokens (project/service token preferred)
APP_BASE_URL           # the public https://....up.railway.app URL
```

The production deploy workflow (`.github/workflows/deploy.yml`) requires the `production` GitHub Environment with required reviewers.

---

## 6. Smoke Test (after deploy)

```bash
# 1. Health
curl -s https://$APP_BASE_URL/health | jq

# 2. Pricing
curl -s https://$APP_BASE_URL/pricing | jq

# 3. Create a real checkout session
curl -s -X POST https://$APP_BASE_URL/create-checkout-session \
  -H 'Content-Type: application/json' \
  -d '{"plan":"audit","email":"launch-test@garcar.com","source":"launch-day"}' | jq
```

You should receive a `checkout_url`. Open it and complete a test payment if desired.

---

## Current Routes (source of truth = app/main.py)

| Method | Path                      | Purpose                          |
|--------|---------------------------|----------------------------------|
| GET    | `/livez`                  | Liveness probe                   |
| GET    | `/readyz`                 | Readiness probe (DB + Stripe)    |
| GET    | `/health`                 | Offer catalog status             |
| GET    | `/pricing`                | Public pricing                   |
| POST   | `/create-checkout-session`| Create Stripe Checkout session   |
| POST   | `/stripe-webhook`         | Stripe events (HMAC verified)    |
| GET    | `/download`               | Signed download (entitlement)    |
| GET    | `/success`                | Post-payment success page        |
| GET    | `/mrr`                    | MRR summary (requires Supabase)  |

---

## Fail-closed behavior

If `ENVIRONMENT=production` and any required secret is missing, the process **exits on startup**.  
This is intentional. Do not bypass it.
