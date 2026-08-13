# Garcar AutoKey — Secret Contract & OIDC/Keyless Authentication Design

> **Authoritative secret names: [SECRETS.md](./SECRETS.md)**

## How it works

1. You set secrets **once** in GitHub → Settings → Secrets → Actions.
2. `autokey-bootstrap.yml` runs **once** manually to wire everything end-to-end.
3. Every production deployment goes through the **production** GitHub Environment,
   which requires a human approver — **no automatic merges or deploys**.

## OIDC / Keyless Authentication Design

GitHub Actions supports OIDC token exchange so that Actions workflows can
authenticate to cloud providers **without storing long-lived secrets**.

### How OIDC works

```
GitHub Actions runner
  │  issues short-lived JWT (OIDC token) signed by GitHub
  ▼
Cloud provider (Railway, AWS, GCP, Azure …)
  │  verifies the JWT against GitHub's JWKS endpoint
  │  grants a scoped, time-limited credential
  ▼
Workflow uses the credential — no secret stored in GitHub
```

### Manual one-time trust setup (required by a human)

> **These steps must be performed by an authorized human outside this
> repository.  The Copilot agent cannot and will not perform them.**

#### Railway (current provider)

Railway does not yet support OIDC token exchange natively.  Until it does,
use a `RAILWAY_TOKEN` scoped to this service stored in GitHub Secrets.

Checklist:
- [ ] Create a Railway service token scoped to `garcar-payments` only (not an account-wide token)
- [ ] Store it as `RAILWAY_TOKEN` in GitHub repository secrets
- [ ] Rotate it quarterly

#### Future providers (AWS / GCP / Azure)

When migrating to a provider that supports OIDC:

1. **AWS** — Create an IAM OIDC Identity Provider pointing at
   `https://token.actions.githubusercontent.com` with audience `sts.amazonaws.com`.
   Create an IAM role that trusts subject
   `repo:Garrettc123/garcar-payments:environment:production`.

2. **GCP** — Add a Workload Identity Pool, configure provider with issuer
   `https://token.actions.githubusercontent.com`.  Bind the pool to a service
   account with least-privilege IAM roles.

3. **Azure** — Register a federated identity credential on a managed identity
   using subject `repo:Garrettc123/garcar-payments:environment:production`.

The `deploy.yml` workflow already requests `id-token: write` so it can
exchange for OIDC credentials once a provider is configured.

## Required secrets (set once)

See [SECRETS.md](./SECRETS.md) for the canonical list.

## Unsafe behaviours removed

| Removed | Why |
|---------|-----|
| Auto-approve-and-merge workflow | PRs must have human review |
| Auto-deploy on every push to main | Replaced by manual-approval production environment |
| Secret values in `.env.example` / `.env.template` | Names only — no placeholder or real values |
| Hardcoded API keys in `backend/main.py` | Replaced by `app/settings.py` |
| Automatic Stripe webhook secret rotation on every push | Removed — rotation is a manual operator action |

## Production startup validation

`app/settings.py` calls `assert_production_ready()` at lifespan startup.
If `ENVIRONMENT=production` and any required secret is missing, the process
exits with a clear error message and a non-zero exit code.  The container
will restart, surface the error in logs, and **never serve traffic in a
broken state**.

Required for production:
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `APP_BASE_URL` (not localhost)
- `DOWNLOAD_SIGNING_SECRET`
- All five `STRIPE_PRICE_*` keys
