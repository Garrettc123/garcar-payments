# 🚀 Garcar Payments — Activation Checklist

This document is the **exact** step-by-step to go from code to live payments.

---

## Step 1 — Create Stripe Products (10 min)

1. Go to [https://dashboard.stripe.com/products](https://dashboard.stripe.com/products)
2. Click **"+ Add product"** for each MARS tier:

| Product Name        | Price    | Billing  |
|---------------------|----------|----------|
| MARS Starter        | $497/mo  | Monthly  |
| MARS Professional   | $1,497/mo| Monthly  |
| MARS Enterprise     | $4,997/mo| Monthly  |
| MARS Sovereign      | $14,997/mo| Monthly |

3. After creating each product, copy the **Price ID** (starts with `price_`)
4. Save them — you'll add them in Step 3.

---

## Step 2 — Configure Stripe Webhook (5 min)

1. Go to [https://dashboard.stripe.com/webhooks](https://dashboard.stripe.com/webhooks)
2. Click **"+ Add endpoint"**
3. Endpoint URL: `https://YOUR_RAILWAY_URL/payments/webhook/stripe`
4. Select these events:
   - `customer.subscription.created`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_failed`
   - `checkout.session.completed`
5. Click **"Add endpoint"** → copy the **Signing secret** (`whsec_...`)

---

## Step 3 — Set Railway Environment Variables (5 min)

1. Go to [https://railway.app](https://railway.app) → `garcar-payments` project → **Variables** tab
2. Add ALL of these:

```
STRIPE_SECRET_KEY          = sk_live_YOUR_LIVE_KEY
STRIPE_WEBHOOK_SECRET      = whsec_YOUR_WEBHOOK_SECRET
STRIPE_PRICE_MARS_STARTER       = price_STARTER_ID
STRIPE_PRICE_MARS_PROFESSIONAL  = price_PROFESSIONAL_ID
STRIPE_PRICE_MARS_ENTERPRISE    = price_ENTERPRISE_ID
STRIPE_PRICE_MARS_SOVEREIGN     = price_SOVEREIGN_ID
NOTION_TOKEN               = secret_YOUR_NOTION_TOKEN
LINEAR_API_KEY             = lin_api_YOUR_KEY
RAILWAY_DEPLOY_URL         = https://YOUR_APP.up.railway.app
```

---

## Step 4 — Set GitHub Secrets (3 min)

1. Go to [https://github.com/Garrettc123/garcar-payments/settings/secrets/actions](https://github.com/Garrettc123/garcar-payments/settings/secrets/actions)
2. Add:
   - `RAILWAY_TOKEN` — from Railway dashboard → Account → Tokens
   - `RAILWAY_DEPLOY_URL` — your Railway app URL
   - `STRIPE_SECRET_KEY`
   - `STRIPE_WEBHOOK_SECRET`
   - `NOTION_TOKEN`
   - `LINEAR_API_KEY`

---

## Step 5 — Deploy (2 min)

Push any commit to `main` OR go to **Actions** tab → **Deploy Garcar Payments** → **Run workflow**.

The pipeline will:
1. ✅ Run tests
2. 🔒 Scan for hardcoded secrets
3. 🚂 Deploy to Railway
4. 💓 Verify `/health` returns 200

---

## Step 6 — Verify Live (2 min)

```bash
# Health check
curl https://YOUR_APP.up.railway.app/health

# MARS tiers API
curl https://YOUR_APP.up.railway.app/mars/api/tiers

# MRR dashboard
curl https://YOUR_APP.up.railway.app/payments/mrr

# MARS landing page
open https://YOUR_APP.up.railway.app/mars/
```

---

## Live Endpoints After Activation

| Endpoint | Purpose |
|----------|---------|
| `/mars/` | MARS API pricing landing page |
| `/mars/checkout/starter` | $497/mo checkout |
| `/mars/checkout/professional` | $1,497/mo checkout |
| `/mars/checkout/enterprise` | $4,997/mo checkout |
| `/mars/checkout/sovereign` | $14,997/mo checkout |
| `/mars/api/tiers` | JSON tiers for frontend |
| `/payments/webhook/stripe` | Stripe webhook receiver |
| `/payments/payment/create-link` | One-time payment link |
| `/payments/mrr` | Live MRR dashboard |
| `/health` | Service health |

---

**Owner:** Garrett Carroll — Garcar Enterprise LLC, Grandview TX  
**Revenue target:** $50K–$100K MRR via MARS API subscriptions
