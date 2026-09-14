# Garcar Autonomous Wiring TODO for garcar-payments

Role: `payments`

_Live fan-out: 2026-09-12 (wet / CASH_LOCK)_

## Required Garcar Base Contract
- [x] `/health` — present (enhanced with system/version/timestamp)
- [x] `/meta` — **added** (role payments, contract_version 1.0.0)
- [x] `/metrics` — **added** (JSON counters)
- [x] `/events` — **added** (in-memory ring)

## Event Bus Wiring
- [ ] Emit required events for this role (`garcar.garcar-payments.{event_type}`).
- [ ] Consume required arbitrage/control-plane events.
- Remaining: NATS/Redis Streams client; Zeus/Atlas dashboard visibility; contract+event tests.

## Current Full-Stack Components
- backend_api: FastAPI (`main.py`)
- frontend_ui: None
- payment_hook: Stripe
- event_bus_connected: False (in-memory ring only)
- observability_connected: False

## Wiring Tasks
1. ~~Add or verify Garcar Base Contract endpoints.~~ **DONE**
2. Add NATS/Redis Streams client and emit/consume required topics.
3. Ensure metrics/events appear in Zeus/Atlas dashboards.
4. Add tests for contract + event wiring.

## Safety
- Draft PR only. Do not auto-merge.
- Respect CASH_LOCK: no live spend / no silent outbound.
