# Garcar — Full End-to-End Cloudflare Auto Configure

One workflow replaces the entire Railway bootstrap + secret sync + Stripe wiring + deploy.

## Prerequisites (do once)

1. Create a Cloudflare API Token  
   → dash.cloudflare.com → My Profile → API Tokens  
   → template **Edit Cloudflare Workers** (or custom: Workers Scripts Edit + Account Settings Read)

2. Add these secrets to the GitHub repo  
   → https://github.com/Garrettc123/garcar-payments/settings/secrets/actions

   | Secret | Required |
   |--------|----------|
   | `CLOUDFLARE_API_TOKEN` | **Yes** |
   | `STRIPE_SECRET_KEY` | **Yes** |
   | `APP_BASE_URL` | Recommended (or pass as workflow input) |
   | `SUPABASE_*`, `LINEAR_*`, `NOTION_*`, etc. | Optional |

3. Files already on branch `cloudflare-autoconfigure`:
   - `wrangler.toml`
   - `scripts/autokey_bootstrap_cf.py`
   - `app/entry.py`
   - `.github/workflows/auto-configure.yml`
   - `.github/workflows/deploy-cloudflare.yml`

## First-time run

1. Merge this branch (or run from it)
2. Go to **Actions → Full End-to-End Auto Configure (Cloudflare)**
3. Click **Run workflow**
4. Fill in:
   - `environment` = production
   - `app_base_url` = your Workers URL
5. Approve the production environment if required
6. Wait ~2–4 minutes

What happens automatically:

- Creates `stripe-events` + `stripe-events-dlq` queues
- Creates / reuses Stripe products & prices
- Registers the Stripe webhook against your Workers URL
- Pushes every secret into Cloudflare Workers
- Deploys the Worker
- Health-checks `/health`

## Ongoing deploys

Use **Deploy to Cloudflare (Production)** (manual approval).  
No more Railway.
