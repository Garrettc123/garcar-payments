-- Garcar Payments — D1 initial schema
-- Apply with:
--   npx wrangler d1 execute garcar-payments-db --file=migrations/0001_d1_init.sql

CREATE TABLE IF NOT EXISTS billing_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    customer_id TEXT,
    subscription_id TEXT,
    invoice_id TEXT,
    payload TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS fulfillment_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stripe_event_id TEXT NOT NULL UNIQUE,
    checkout_session_id TEXT,
    plan TEXT,
    customer_email TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    email_sent INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL
);

CREATE TABLE IF NOT EXISTS download_entitlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stripe_event_id TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    plan TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_billing_event_id ON billing_events(event_id);
CREATE INDEX IF NOT EXISTS idx_fulfillment_status ON fulfillment_jobs(status);
CREATE INDEX IF NOT EXISTS idx_entitlement_email_plan ON download_entitlements(customer_email, plan);
