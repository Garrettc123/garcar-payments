# garcar-payments

Stripe + FastAPI + Railway payment service for Garcar Enterprise.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Service health check |
| GET | /pricing | List Stripe plans |
| POST | /create-checkout-session | Start Stripe checkout |
| POST | /stripe-webhook | Receive Stripe events |
| GET | /success | Post-payment landing |

## Required Secrets (GitHub Actions)

| Secret | Source |
|--------|--------|
| `RAILWAY_TOKEN` | railway.app → Account → Tokens |
| `STRIPE_SECRET_KEY` | Stripe Dashboard → Developers → API Keys |
| `STRIPE_WEBHOOK_SECRET` | Auto-set after register-stripe-webhook.yml runs |
| `STRIPE_PRICE_STARTER` | Stripe Dashboard → Products |
| `STRIPE_PRICE_PRO` | Stripe Dashboard → Products |
| `STRIPE_PRICE_AGENCY` | Stripe Dashboard → Products |
| `APP_BASE_URL` | Railway dashboard → your service domain |

## Deploy

Every push to `main` deploys automatically via GitHub Actions.

```bash
git push origin main
```

## Local dev

```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```
