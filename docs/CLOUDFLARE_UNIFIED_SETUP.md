# Unified Cloudflare setup for Garcar Enterprise

Status: **prepared, not deployed**. This document inventories source-controlled
intent. It does **not** establish that a Cloudflare zone, Worker, Queue, route,
D1 database, or Stripe webhook is live.

## Cloudflare's role in the stack

| Responsibility | Existing source | Proposed Cloudflare role |
| --- | --- | --- |
| Payment ingestion | `garcar-payments/wrangler.toml` | **One** canonical Stripe webhook Worker, durable Queue + DLQ; optional D1 after migration |
| Lead capture | `garcar-enterprise-production/wrangler.toml` | Dedicated `garcar-lead-capture` Worker, separate scoped secrets |
| Operator events | `garcar-operator-fabric/wrangler.jsonc` | Dedicated webhook Worker, Queues, KV and Workflows; approvals remain enforced |
| RHNS agents | `garcar-rhns-core/PIXEL10-BOOTSTRAP.md` | Optional isolated Workers, after ownership and deployment audit; **do not** create a second active Stripe receiver |
| Website/storefront | Existing Vercel projects | Keep Vercel as origin. Add Cloudflare DNS/proxy only for a **verified, owned** domain, using documented provider settings |
| Backend systems | Existing Railway projects | Keep Railway for long-running Python/container workloads; use Cloudflare only as verified edge/router if needed |
| Operator access | Private control plane | Prefer Cloudflare Access / Zero Trust for human admin surfaces, **not** in front of Stripe webhook endpoints without a compatible service-auth design |

## Step 1 — Establish account/zone ownership (human Cloudflare access)

1. Sign in at https://dash.cloudflare.com and identify the **actual account ID** and managed zones.
2. Verify domain ownership and authoritative nameservers **before** changing DNS. Never assume a historic hostname is currently owned or delegated.
3. Create a **least-privilege read-only token** for inventory: Workers Scripts Read, Queues Read and D1 Read for the chosen Cloudflare account, according to the permissions available in the Cloudflare dashboard. Do not use a global API key or an account-wide token with token-creation rights.
4. Store `CLOUDFLARE_API_TOKEN` as a GitHub Actions secret at
   https://github.com/Garrettc123/garcar-payments/settings/secrets/actions.
   Store `CLOUDFLARE_ACCOUNT_ID` as a GitHub Actions variable or secret.
   **Do not paste credentials into a chat, issue, PR, log, or repository file.**
5. Run **Actions → Cloudflare Readiness (read-only) → Run workflow** after this branch is merged. The job only calls Cloudflare **GET** endpoints and reports recognizable Worker, Queue and D1 names. It does not read secret values or alter remote resources.

The readiness token is **not** a deployment token. A separate, scoped deployment credential may be added later after permissions and environment protections are reviewed.

## Step 2 — Reconcile infrastructure before deployment

Expected candidate Workers are `garcar-payments`, `garcar-lead-capture`,
`garcar-operator-fabric`, and RHNS edge workers. Candidate Queues include
`stripe-events`, `stripe-events-dlq`, `garcar-ops-queue`,
`garcar-notify-queue`, and `garcar-dlq`.

Cloudflare inventory is **account-scoped**, so "not found" does not establish
absence from another account. Inspect any duplicates, account scopes and
environment bindings before provisioning new resources. The `garcar-payments`
D1 binding is commented out in its current `wrangler.toml`; a database ID has
not been proven. The operator-fabric KV ID is a placeholder in source control.
Do **not** deploy those bindings until replaced with genuine account resource IDs.

### Canonical Stripe ingress

* Select exactly one Worker URL as the payment webhook destination, subject to
  observed health and valid signing-secret configuration.
* Keep the current Stripe endpoint in place until a verified replacement can
  process authenticated events, deduplicate event IDs, enqueue durably, and
  recover from failure via the DLQ.
* Check both Stripe account identity and event delivery results. Never treat a
  functioning `/health` endpoint as proof of successful payment settlement.
* **Do not run** `scripts/autokey_bootstrap_cf.py` in its current state.
  It deletes a matching existing Stripe webhook endpoint before creating a new
  one, while queue creation failures can be ignored. This requires a separate,
  reviewed non-destructive migration patch.
* Avoid transient Cloudflare Quick Tunnels as the authoritative live Stripe
  webhook URL.

### Application routing and security

* Use Cloudflare proxy/routing only for DNS zones verified under the owned
  Cloudflare account. Preserve existing Railway/Vercel hostnames and SSL settings
  until TLS and routing have been validated.
* Put human operator and private admin routes behind Cloudflare Access.
  Public signed webhooks must retain compatible unauthenticated network ingress,
  then verify their provider signatures **before** processing events.
* Configure separate production/staging Worker names, Queues, Secrets and route
  ownership. Do not automatically promote staging data or credentials.
* Apply rate limiting and WAF rules only after validating legitimate webhook,
  OAuth and health-check traffic paths.
* Use Cloudflare encrypted Worker secrets; never commit token values to
  `wrangler.toml`, `wrangler.jsonc`, `.env`, logs or documentation.

## Step 3 — Production acceptance gate

No DNS switch, payment-webhook change, bulk deployment, or existing resource
deletion is authorized by the read-only inventory. A production change requires:

- [ ] Confirmed Cloudflare account, owned zone, and current DNS/SSL routing.
- [ ] Read-only Worker/Queue/D1 inventory completed for the account.
- [ ] Required Workers and Queues provisioned with real IDs; version and rollback known.
- [ ] Worker secrets provisioned through the proper scope and validated without disclosing values.
- [ ] Live health/ready checks target the *actual* Worker URL.
- [ ] Stripe account and active webhook destination match; delivery, signature
      checks, idempotency and queue handling are observed.
- [ ] Existing Vercel/Railway services remain reachable after any DNS change.
- [ ] Staging and production safety approvals, rollback and incident handling verified.

## References

* Cloudflare Workers configuration:
  https://developers.cloudflare.com/workers/wrangler/configuration/
* Workers environments and routes:
  https://developers.cloudflare.com/workers/wrangler/environments/
* Secrets:
  https://developers.cloudflare.com/workers/configuration/secrets/
* Least-privilege Cloudflare API tokens:
  https://developers.cloudflare.com/fundamentals/api/get-started/create-token/
