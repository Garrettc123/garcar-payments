# Garcar Payments — Single Source of Truth for Secrets

**One place. Everything else pulls from it.**

```
https://github.com/Garrettc123/garcar-payments/settings/secrets/actions
```

Set these secrets **once**. The Autokey bootstrap workflow then pushes them to Railway, registers the Stripe webhook, and keeps the live service in sync. No other system should ever hold a duplicate long-lived secret.

---

## Canonical Secrets (exact names — case sensitive)

### Required (bootstrap will fail without these)

| Secret | Purpose | Where to get it |
|--------|---------|-----------------|
| `RAILWAY_TOKEN` | Deploy + variable sync | railway.app → Account → Tokens |
| `STRIPE_SECRET_KEY` | Live Stripe API | dashboard.stripe.com → Developers → API keys |
| `APP_BASE_URL` | Service origin (no trailing slash) | Railway service domain, e.g. `https://garcar-payments.up.railway.app` |

### Stripe Price IDs (required for checkout to work)

| Secret | Offer |
|--------|-------|
| `STRIPE_PRICE_AUDIT` | One-time Operational Audit |
| `STRIPE_PRICE_DEALDESK` | One-time AI Deal Desk Setup |
| `STRIPE_PRICE_STARTER` | Starter subscription |
| `STRIPE_PRICE_PRO` | Pro subscription |
| `STRIPE_PRICE_AGENCY` | Agency / managed subscription |

### Auto-managed / optional

| Secret | Notes |
|--------|-------|
| `STRIPE_WEBHOOK_SECRET` | Written automatically by `autokey-bootstrap` if missing |
| `GARCAR_PAYMENTS_URL` | **Alias** of `APP_BASE_URL`. Set to the same value so older workflows keep working |
| `LINEAR_API_KEY` | Linear GraphQL |
| `LINEAR_TEAM_ID` | Linear team |
| `NOTION_TOKEN` | Notion integration token |
| `NOTION_REVENUE_DB_ID` | Revenue snapshot database |
| `SUPABASE_URL` | Ledger + MRR |
| `SUPABASE_SERVICE_KEY` | Service role key |
| `DATABASE_URL` | Postgres (if used) |
| `CORS_ALLOW_ORIGINS` | Usually `*` for early launch |

---

## One-time activation sequence

1. Add every secret above at the link at the top of this file.
2. Run **Autokey Bootstrap** once:
   https://github.com/Garrettc123/garcar-payments/actions/workflows/autokey-bootstrap.yml
3. Done. Railway now has the same values. Stripe webhook is registered. Health checks and scheduled jobs can see the secrets.

After that, every push to `main` and every scheduled workflow simply reads from this same GitHub secrets store. Never copy-paste secrets into Railway, Notion, or Linear again.

---

## Naming rules (enforced)

- Never invent new secret names without updating this file and `autokey-bootstrap.yml`.
- `APP_BASE_URL` is the primary service URL. `GARCAR_PAYMENTS_URL` is only a compatibility alias.
- There are **no** `STRIPE_PRICE_MARS_*` secrets. Those names are retired.
- Secrets are never logged. Workflows that print secret values are forbidden.
