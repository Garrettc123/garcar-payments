# Garcar Autokey System

Zero copy-paste secret management for garcar-payments.

> **Authoritative list of every secret name lives in [SECRETS.md](./SECRETS.md).**

## How it works

1. You set secrets **once** in GitHub → Settings → Secrets → Actions
2. `autokey-bootstrap.yml` runs **once** manually to wire everything end-to-end
3. Every push to `main` after that auto-deploys, syncs secrets, and self-checks

## Required secrets (set once, never again)

See the full canonical table in [SECRETS.md](./SECRETS.md).

Minimum set for a working deployment:

| Secret | Where to get it |
|--------|-----------------|
| `RAILWAY_TOKEN` | railway.app → Account → Tokens |
| `STRIPE_SECRET_KEY` | Stripe Dashboard → Developers → API Keys |
| `APP_BASE_URL` | Railway dashboard → your service domain |
| `STRIPE_PRICE_AUDIT` | Stripe Product/Price |
| `STRIPE_PRICE_DEALDESK` | Stripe Product/Price |
| `STRIPE_PRICE_STARTER` | Stripe Product/Price |
| `STRIPE_PRICE_PRO` | Stripe Product/Price |
| `STRIPE_PRICE_AGENCY` | Stripe Product/Price |

`STRIPE_WEBHOOK_SECRET` is generated and written back by the bootstrap workflow itself.

## First-time setup

```
1. Add secrets at:
   https://github.com/Garrettc123/garcar-payments/settings/secrets/actions

2. Run the bootstrap workflow:
   https://github.com/Garrettc123/garcar-payments/actions/workflows/autokey-bootstrap.yml
   → Click "Run workflow" → Select environment → Run

3. Done. The workflow:
   ✅ Validates all secrets exist
   ✅ Deploys to Railway
   ✅ Syncs all env vars
   ✅ Health checks the live service
   ✅ Registers Stripe webhook
   ✅ Writes STRIPE_WEBHOOK_SECRET back to Railway automatically
```

## After first run

Every `git push origin main` triggers deploy workflows automatically.
No terminal. No copy-paste. No manual steps.
