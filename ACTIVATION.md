# 🚀 Garcar Payments — Activation Checklist

This document is the **exact** step-by-step to go from code to live payments.
All secrets live in **one place**: GitHub Actions secrets. See [SECRETS.md](./SECRETS.md).

---

## Step 1 — Create Stripe Products (10 min)

1. Go to [https://dashboard.stripe.com/products](https://dashboard.stripe.com/products)
2. Create the five live offers used by the code:

| Offer key | Product Name | Mode | Typical price |
|-----------|--------------|------|---------------|
| `audit` | Operational Audit | one-time | $197 |
| `dealdesk` | AI Deal Desk Setup | one-time | $497 |
| `starter` | Starter Automation | subscription | monthly |
| `pro` | Pro Automation | subscription | monthly |
| `agency` | Agency Automation | subscription | monthly |

3. After creating each product, copy the **Price ID** (`price_…`).
4. These become the five `STRIPE_PRICE_*` secrets in Step 3.

---

## Step 2 — Set GitHub Secrets (the single source of truth)

1. Go to [https://github.com/Garrettc123/garcar-payments/settings/secrets/actions](https://github.com/Garrettc123/garcar-payments/settings/secrets/actions)
2. Add every secret listed in [SECRETS.md](./SECRETS.md).

Minimum required:

```
RAILWAY_TOKEN
STRIPE_SECRET_KEY
APP_BASE_URL
STRIPE_PRICE_AUDIT
STRIPE_PRICE_DEALDESK
STRIPE_PRICE_STARTER
STRIPE_PRICE_PRO
STRIPE_PRICE_AGENCY
```

Optional but recommended: `LINEAR_API_KEY`, `LINEAR_TEAM_ID`, `NOTION_TOKEN`, `NOTION_REVENUE_DB_ID`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `CORS_ALLOW_ORIGINS`, and set `GARCAR_PAYMENTS_URL` = same value as `APP_BASE_URL`.

---

## Step 3 — Run Autokey Bootstrap (2 min)

1. Open https://github.com/Garrettc123/garcar-payments/actions/workflows/autokey-bootstrap.yml
2. Click **Run workflow** → choose `production` → Run.

The workflow will:
- Validate secrets
- Deploy to Railway
- Push every env var into Railway
- Health-check `/health`
- Register the Stripe webhook at `$APP_BASE_URL/stripe-webhook`
- Write `STRIPE_WEBHOOK_SECRET` back to Railway

You do **not** need to touch the Railway Variables UI after this.

---

## Step 4 — Verify Live (2 min)

```bash
# Health check
curl https://YOUR_APP.up.railway.app/health

# Pricing catalog
curl https://YOUR_APP.up.railway.app/pricing

# MRR dashboard
curl https://YOUR_APP.up.railway.app/mrr
```

---

## Live Endpoints After Activation

| Endpoint | Purpose |
|----------|---------|
| `/health` | Service health + configured offers |
| `/pricing` | Public plan catalog |
| `/create-checkout-session` | Start Stripe Checkout |
| `/stripe-webhook` | Stripe webhook receiver |
| `/mrr` | Live MRR dashboard |
| `/success` | Post-payment success |

---

**Owner:** Garrett Carroll — Garcar Enterprise LLC, Grandview TX
