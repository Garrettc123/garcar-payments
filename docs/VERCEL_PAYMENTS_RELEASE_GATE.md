# Vercel deployment contract — Garcar Payments

## Scope
`garcar-payments` is documented as the payment control plane, with signed Stripe
webhooks, Checkout, recurring revenue, and durable fulfillment. The Vercel
entrypoint in `pyproject.toml` is `app.main:app`, not
`backend.mars_tiers:app`. The MARS module is a separate subscription storefront
and does **not** implement the canonical `/stripe-webhook` contract.

## Important platform boundary
Vercel hosts the FastAPI request handler; it does not automatically launch the
`app.supervisor` process. This repository's Railway and Docker instructions
run `python -m app.supervisor` to host the API and the durable fulfillment
worker together. A successful Vercel build or GET /health therefore cannot
certify fulfillment. Do not route production Stripe events to Vercel before
verifying that its API and an independently running authorized worker use
the same persistent database and that new FulfillmentJob rows are consumed.

## Required pre-promotion checks
1. Establish the actual owning Vercel team/project, Git-linked repository and
   intended production branch. Confirm the target Git SHA exactly.
2. Run repository tests including
   `pytest tests/test_vercel_entrypoint_contract.py -q` and the complete suite.
3. Stage a non-production deployment; verify import/startup with intended
   environment and `/livez`, `/readyz`, and `/health`.
   `/readyz` must fail with HTTP 503 when dependencies are not ready.
4. Verify that POST `/stripe-webhook` with no signing secret refuses requests,
   invalid Stripe signatures are rejected, and only verified events are accepted.
   Use only Stripe test-mode fixtures, with no production charge or webhook
   destination change during this validation.
5. Verify one controlled test event is persisted and its fulfillment job
   is processed **once** by a running worker, then verify its durable receipt.
   Dispatch acceptance is not job completion.
6. Verify that checkout only refers to configured, approved Stripe Price IDs;
   confirm that an unconfigured product cannot issue a live charge.
7. Only after all checks pass, use a reviewed and approved production
   deployment. Verify post-deploy route contract and webhook destination.
8. Reconcile event IDs, worker outcomes, billing records, and deployment SHA
   before reporting production as operational.

## Status vocabulary
- CONFIGURED: required settings and route contract exist.
- DEPLOYED: provider returned deployment ID, target, SHA and READY.
- HEALTHY: dependency checks succeeded within the freshness window.
- OPERATIONAL: signed test event passed from API through durable worker receipt.
- UNKNOWN: no fresh evidence; never emit synthetic success or revenue.

The code review/PR is not permission to modify Stripe webhook endpoints,
perform paid transactions, change secrets, or deploy to production.
