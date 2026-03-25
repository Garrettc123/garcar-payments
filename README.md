# 💳 Garcar Payments Engine

Autonomous payment infrastructure for **Garcar Enterprise** — Stripe webhook receiver, Linear issue lifecycle automation, Notion MRR sync, Railway deployment, and self-healing CI/CD.

---

## Architecture

```
Stripe Event
    │
    ▼
/webhook/stripe (FastAPI)
    │
    ├── invoice.paid          → Linear: In Progress + contract + ledger
    ├── subscription.created  → Linear: New issue (priority 2)
    ├── payment_failed        → Linear: At Risk (priority 1)
    ├── subscription.deleted  → Linear: Cancelled + win-back note
    └── checkout.completed    → Contract + ledger
    │
    ▼
Notion MRR Sync (every hour via GitHub Actions)
```

---

## Secrets required

| Secret | Description |
|--------|-------------|
| `STRIPE_SECRET_KEY` | Stripe live secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `LINEAR_API_KEY` | Linear personal API token |
| `LINEAR_TEAM_ID` | Linear team UUID (pre-filled: Garrettc) |
| `LINEAR_PROJECT_ID` | Linear project UUID (pre-filled: Tree of Life) |
| `LINEAR_STATE_IN_PROGRESS` | Linear state UUID for "In Progress" |
| `LINEAR_STATE_AT_RISK` | Linear state UUID for "At Risk" |
| `LINEAR_STATE_CANCELLED` | Linear state UUID for "Cancelled" |
| `NOTION_TOKEN` | Notion integration token |
| `NOTION_REVENUE_DB_ID` | Notion database UUID for MRR snapshots |
| `RAILWAY_TOKEN` | Railway deploy token |
| `GARCAR_PAYMENTS_URL` | Deployed service URL for health checks |

---

## Local development

```bash
cp .env.template .env
# fill in .env values
pip install -r requirements.txt
uvicorn backend.payments:app --reload --port 8007
```

## Deploy

Push to `main` → GitHub Actions auto-deploys to Railway via `deploy.yml`.

Health monitor runs every 15 minutes. If the service goes down, `self-heal.yml` auto-redeploys and creates a Linear alert.

Notion MRR sync runs every hour via `notion-sync.yml`.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/payment/create-link` | Create a Stripe payment link |
| POST | `/webhook/stripe` | Stripe webhook receiver |
| GET | `/mrr` | Current MRR from ledger |
| GET | `/health` | Health check |
