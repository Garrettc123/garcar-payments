# GAR-496 — Railway Deployment Steps
## garcar-payments — Stripe Payment Gateway

---

## 5-Minute Deploy

### Step 1 — Create Railway service
1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select `Garrettc123/garcar-payments`
3. Railway auto-detects the `Dockerfile` → confirm builder = Dockerfile
4. Service name: `garcar-payments`
5. Click **Deploy**

### Step 2 — Set these 5 env vars in Railway → Variables

```
STRIPE_SECRET_KEY        sk_live_...          (Stripe Dashboard → Developers → API keys)
STRIPE_WEBHOOK_SECRET    whsec_...            (fill in Step 4 below)
LINEAR_API_KEY           lin_api_...          (Linear → Settings → API)
SLACK_WEBHOOK_URL        https://hooks.slack.com/services/...
NOTION_TOKEN             secret_...           (Notion integration token)
```

### Step 3 — Verify health
```bash
curl https://<your-railway-url>.railway.app/health
# Expected: {"status": "running", "service": "garcar-payments"}
```

### Step 4 — Register Stripe webhook
1. [Stripe → Developers → Webhooks](https://dashboard.stripe.com/webhooks) → **Add endpoint**
2. URL: `https://<your-railway-url>.railway.app/payments/webhook/stripe`
3. Select events:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.deleted`
   - `invoice.paid`
   - `invoice.payment_failed`
4. Copy **Signing secret** (`whsec_...`)
5. Add to Railway Variables: `STRIPE_WEBHOOK_SECRET = whsec_...`
6. Railway auto-redeploys

### Step 5 — Set GitHub Secrets (enables CI/CD)
In `garcar-payments` repo → Settings → Secrets → Actions:
```
RAILWAY_TOKEN         (Railway → Account Settings → Tokens)
RAILWAY_DEPLOY_URL    https://<your-railway-url>.railway.app
```

### Step 6 — Run smoke test
Actions tab → **Stripe Webhook Smoke Test** → **Run workflow**

All 5 checks must pass. GAR-496 = Done.

---

## Route Reference

| Route | Purpose |
|---|---|
| `GET /health` | Railway healthcheck |
| `POST /payments/webhook/stripe` | Stripe webhook (HMAC-verified) |
| `GET /payments/mrr` | Current MRR from ledger |
| `POST /payments/payment/create-link` | Dynamic payment link |
| `GET /mars/` | MARS API landing |
| `GET /mars/api/tiers` | Pricing tiers |
