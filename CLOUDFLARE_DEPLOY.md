# Cloudflare Workers — Primary Launch Path

**Railway is bypassed.**  
`garcar-payments` runs on Cloudflare Workers for launch day.

---

## Why Cloudflare

- Global edge (low latency for checkout)
- Durable Queues for Stripe webhooks (no lost events)
- Python Workers with lazy-loaded FastAPI
- AutoKey script creates products, prices, webhook, and secrets in one shot
- No long-running container cost while idle

---

## 1. Prerequisites (GitHub Secrets)

```
CLOUDFLARE_API_TOKEN     # Account → API Tokens → Edit Cloudflare Workers
STRIPE_SECRET_KEY        # sk_live_...
```

Optional (AutoKey will create prices if missing):
```
STRIPE_PRICE_AUDIT
STRIPE_PRICE_DEALDESK
STRIPE_PRICE_STARTER
STRIPE_PRICE_PRO
STRIPE_PRICE_AGENCY
DOWNLOAD_SIGNING_SECRET
RESEND_API_KEY
APP_BASE_URL             # defaults to https://garcar-payments.<subdomain>.workers.dev
```

---

## 2. Deploy the Worker

```bash
gh workflow run deploy-cloudflare.yml --repo Garrettc123/garcar-payments --ref main
```

Or Actions tab → **Deploy to Cloudflare (Production)** → Run workflow.

---

## 3. Bootstrap (prices + webhook + secrets)

From a machine that has the secrets:

```bash
export STRIPE_SECRET_KEY=sk_live_...
export CLOUDFLARE_API_TOKEN=...
# optional
export APP_BASE_URL=https://garcar-payments.<your-subdomain>.workers.dev

python scripts/autokey_bootstrap_cf.py
```

This will:
- Create / reuse the five Stripe products & prices
- Ensure `stripe-events` + DLQ queues exist
- Register the webhook at `$APP_BASE_URL/stripe-webhook`
- Push every secret into the Worker via `wrangler secret put`

---

## 4. Smoke Test

```bash
URL=https://garcar-payments.<subdomain>.workers.dev

curl -s $URL/health | jq
curl -s $URL/livez | jq
curl -s $URL/pricing | jq

curl -s -X POST $URL/create-checkout-session \
  -H 'Content-Type: application/json' \
  -d '{"plan":"audit","email":"launch@garcar.com","source":"launch-day"}' | jq
```

Expected health response includes `"edge": true` and a low `ms` value.

---

## Performance Notes (current entry.py)

- Health endpoints (`/`, `/health`, `/livez`, `/readyz`) never import FastAPI → sub-10 ms cold start
- Stripe webhook prefers the durable Queue (non-blocking)
- Full FastAPI stack is lazy-loaded only on first business request
- Queue consumer stays minimal; heavy processing can be added later without blocking the edge

---

## Custom Domain (optional)

```bash
npx wrangler domains add payments.garcar.io --name garcar-payments
```

Then set `APP_BASE_URL=https://payments.garcar.io` and re-run AutoKey so the Stripe webhook points at the custom domain.

---

## Fallback

Railway remains possible via `RAILWAY_DEPLOY.md` if you later want a long-running container, but it is no longer required for launch.
