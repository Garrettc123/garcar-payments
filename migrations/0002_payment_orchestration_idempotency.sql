-- Payment orchestration hardening.
-- Remove historical duplicate entitlements before adding the invariant.
DELETE FROM download_entitlements
WHERE id NOT IN (
  SELECT MIN(id)
  FROM download_entitlements
  GROUP BY stripe_event_id, customer_email, plan
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_entitlement_event_email_plan
ON download_entitlements(stripe_event_id, customer_email, plan);
