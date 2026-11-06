# Proof-bound commercial hardening — Garcar Payments
_Date: 2026-11-05 · Status: REVIEW REQUIRED · Base: `main`_

## Verified source boundary
This change enhances **Garrettc123/garcar-payments** rather than creating another checkout or billing service. The canonical components remain `app/main.py` (checkout + signed Stripe ingress), `app/db.py` (durable event and job tables), and `app/worker.py` (Stripe re-verification + fulfillment).

The upstream Garcar Proof Workbench and Capability Kernel source ZIPs referenced in the project document were **not available** for binary/source inspection. Their reported tests are not evidence that this repository is production-ready.

## Implemented change
1. Only a correctly signed `checkout.session.completed` or `checkout.session.async_payment_succeeded` event with `payment_status=paid`, Session ID and a nonblank SKU can propose a durable job. No paid event creates an entitlement directly.
2. The existing worker must independently retrieve the Stripe Checkout Session, confirm its exact ID, `payment_status=paid`, SKU metadata matching the queued job, declared test/live mode, and an allow-listed plan **before entitlement creation or delivery**.
3. Client-supplied Checkout success/cancel redirects must match `APP_BASE_URL` origin exactly. Third-party redirect URLs are rejected before invoking Stripe.
4. The Stripe signing timestamp window rejects timestamps too far in either the future or the past.
5. Each event's ledger record explicitly identifies a signed **observation**. `all_ok=false`, `payment_reconciled=false`, and `revenue_eligible=false`; an event alone is not recognized as settled revenue.

## What this does NOT establish
- Live Stripe checkout success, payout eligibility, connected bank status, or cash receipts.
- A tested entitlement-delivery experience, email exactly-once semantics, or completed customer service.
- Independently reconciled revenue; a future reconciliation worker must join genuine settled charges, disputes, refunds, and payout records without double counting.
- Production release approval, tenant isolation, SOC 2 certification, or completed incident-response drills.

## Local/static test plan
`python -m pytest tests/test_commercial_guard.py tests/test_commercial_integration.py -v`
`python -m pytest tests/ -v`

Expected negative cases: invalid signatures, unpaid/incomplete events, unknown SKUs, mismatched Stripe Session IDs, unknown payment mode, external redirects, expired/future webhook timestamps, duplicate events, and a crashed/retried fulfillment worker.

**Release gate:** CI success AND isolated Stripe test-mode checkout and webhook delivery AND negative tests AND reviewer approval. No production deployment or automatic communication is authorized by this branch.

## Installation and rollback
1. Review this branch as a draft pull request. Preserve current production configuration and database snapshots.
2. Execute tests in CI and an isolated test-mode environment. Confirm webhook secret scopes, event subscriptions, idempotency and required price catalog.
3. Verify no silent fulfillment for `unpaid` or mismatched sessions, and validate expected checkout redirect behavior.
4. Review any dashboards using `gc_ledger.all_ok`: the field is now deliberately false for merely observed events; replace revenue calculations with reconciled charge/payment reporting before merge.
5. Merge only after approval, then deploy through the normal controlled workflow and verify live health without charging a customer.
6. Rollback by reverting the branch's commits, then restoring the prior approved deployment. Do **not** rollback payment event history or replay already-delivered customer messages.

## Outstanding blockers
- The full base repository test suite and GitHub Actions CI must pass. A failing CI is a blocker, even if a previous failure predates this patch.
- Product SKU and Stripe price mapping currently differ across Repo Foundry, Funnel, Revenue OS and Payments. Choose one signed/versioned canonical catalog and publish it before customer activation.
- The `/download` route currently returns an entitlement confirmation message rather than a protected deliverable. Paid services need an authenticated onboarding/delivery workflow before claiming completion.
- The payment ledger needs charge/refund/dispute/payout reconciliation and explicit test/live partitioning.
- Unreviewed direct fulfillment endpoints in other repositories must not bypass the canonical worker.
