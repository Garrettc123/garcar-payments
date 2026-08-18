# Garcar Payments — Operational Runbook

## Health endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /livez` | Liveness — process alive? |
| `GET /readyz` | Readiness — Stripe key + DB reachable? |
| `GET /health` | Legacy — offer catalog status |

## Alerts to set up

| Condition | Action |
|-----------|--------|
| `/readyz` returns non-200 for 2+ minutes | Page on-call; check `DATABASE_URL` and `STRIPE_SECRET_KEY` |
| `FulfillmentJob.status = 'dead'` rows > 0 | Investigate `last_error`; re-queue manually after fix |
| Webhook returns 400 consistently | Verify `STRIPE_WEBHOOK_SECRET` matches Stripe dashboard |
| Email delivery failures | Check `RESEND_API_KEY`; review Resend dashboard |

## Failed fulfillment recovery

```sql
-- Find dead-letter jobs
SELECT id, stripe_event_id, plan, customer_email, attempts, last_error, created_at
FROM fulfillment_jobs
WHERE status = 'dead'
ORDER BY created_at DESC;

-- Re-queue a dead job after fixing the underlying issue
UPDATE fulfillment_jobs SET status = 'pending', attempts = 0, last_error = NULL
WHERE id = <job_id>;
```

## Failed webhook investigation

1. Check Railway logs: `railway logs --service garcar-payments`
2. Check Stripe webhook event log: dashboard.stripe.com → Developers → Webhooks
3. Re-send failed events from Stripe dashboard (they will be deduplicated)

## Database backup

- Automated daily at 02:00 UTC via `.github/workflows/db-backup.yml`
- Encrypted with AES-256-CBC before upload
- Artifacts retained for 30 days in GitHub Actions
- Run restore drill: trigger `db-backup.yml` manually with `restore_drill=true`

## Rotating secrets

1. **STRIPE_WEBHOOK_SECRET** — Delete old webhook in Stripe, create new one, update
   `STRIPE_WEBHOOK_SECRET` in GitHub Secrets and Railway environment variables.
2. **DOWNLOAD_SIGNING_SECRET** — Generate new value:
   ```sh
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   Update GitHub Secrets and Railway. Existing signed links will expire naturally.
3. **BACKUP_ENCRYPTION_KEY** — Update both GitHub Secret and your secure offsite store.
   Re-encrypt the most recent backup with the new key immediately.

## Structured log format

All logs are emitted as JSON lines to stdout:
```json
{"time":"2026-01-01T00:00:00","level":"INFO","logger":"garcar.payments","msg":"webhook_received | event_type=checkout.session.completed | event_id=evt_xxx"}
```

Secrets are never logged.  Customer email is hashed in download logs.

## No-duplicate guarantee

- `BillingEvent.event_id` has a UNIQUE constraint — duplicate webhook events are absorbed with HTTP 200.
- `FulfillmentJob.stripe_event_id` has a UNIQUE constraint — only one job per event.
- `DownloadEntitlement` is guarded by IntegrityError catch — re-runs are idempotent.
