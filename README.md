# garcar-payments

Stripe + FastAPI + Railway payment service for Garcar Enterprise.

This service is the revenue spine for the public Garcar landing page and the recurring SaaS / managed automation product ladder.

## Sellable Offers

| Key | Offer | Stripe mode | Purpose |
|-----|-------|-------------|---------|
| `audit` | Operational Audit | `payment` | One-time $197 lead-leak / missed-call audit |
| `dealdesk` | AI Deal Desk Setup | `payment` | One-time $497 setup package |
| `starter` | Starter Automation Subscription | `subscription` | Entry recurring plan |
| `pro` | Pro Automation Subscription | `subscription` | Professional recurring plan |
| `agency` | Agency Automation Subscription | `subscription` | Managed automation / agency plan |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health check + configured offer keys |
| GET | `/pricing` | Public plan catalog without exposing Stripe price IDs |
| POST | `/create-checkout-session` | Start Stripe checkout for one-time or subscription offers |
| POST | `/stripe-webhook` | Receive Stripe events and persist billing event records |
| GET | `/success` | Post-payment success response |

## Checkout Request

Preferred JSON body:

```json
{
  "plan": "audit",
  "email": "buyer@example.com",
  "source": "garcar-landing",
  "success_url": "https://garcar.io/success.html",
  "cancel_url": "https://garcar.io/checkout.html"
}
```

Backward-compatible query params still work:

```bash
curl -X POST "https://garcar-payments.up.railway.app/create-checkout-session?plan=audit&email=buyer@example.com"
```

## Required Secrets / Variables

| Variable | Source |
|----------|--------|
| `RAILWAY_TOKEN` | railway.app → Account → Tokens |
| `STRIPE_SECRET_KEY` | Stripe Dashboard → Developers → API Keys |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook endpoint secret |
| `STRIPE_PRICE_AUDIT` | Stripe Product/Price for one-time audit |
| `STRIPE_PRICE_DEALDESK` | Stripe Product/Price for one-time setup |
| `STRIPE_PRICE_STARTER` | Stripe recurring price |
| `STRIPE_PRICE_PRO` | Stripe recurring price |
| `STRIPE_PRICE_AGENCY` | Stripe recurring price |
| `APP_BASE_URL` | Railway service domain |
| `DATABASE_URL` | Postgres connection string |
| `CORS_ALLOW_ORIGINS` | Comma-separated allowed origins; use `*` for early launch |

## Deploy

Every push to `main` deploys automatically via GitHub Actions if Railway secrets are configured.

```bash
git push origin main
```

## Local dev

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Revenue Integration Contract

1. Landing page sends `plan` + buyer `email` to `/create-checkout-session`.
2. API returns `checkout_url`.
3. Browser redirects buyer to Stripe Checkout.
4. Stripe sends payment/subscription events to `/stripe-webhook`.
5. Billing events are persisted for onboarding, fulfillment, and revenue reporting.
