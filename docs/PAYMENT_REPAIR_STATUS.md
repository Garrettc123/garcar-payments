# Payment repair status

This commit only repairs paid-checkout gating and delayed-payment dispatch.
Not production-ready: duplicate events can still repeat external side effects.
No live provider test, deployment or financial transaction was performed.

## Remaining release blockers
- Atomic durable inbox keyed by Stripe event ID and livemode/account scope.
- Order uniqueness keyed by checkout session, not event ID alone.
- Durable per-step outbox and deterministic downstream idempotency keys.
- Reconciliation for ambiguous timeouts; never blindly retry non-idempotent sends.
- Cancellation scoped by subscription; partial refunds must not revoke all access.
- Refund mapping by payment intent/charge to the purchased entitlement.
- Guard against out-of-order lifecycle events using authoritative provider state.
- Move CRM, contract and delivery side effects out of the webhook request.
- Apply and test database migrations on an approved target before switching traffic.
- Approved sandbox checkout, delivery, replay, concurrency and failure-recovery tests.
- Independently approved production release with rollback.

Offline tests extract dispatcher functions through AST; they do not test imports,
SDK signature verification, HTTP routes, databases or the real downstream adapters.
Run: python -m unittest discover -s tests -p test_payment_dispatch_repair.py -v
