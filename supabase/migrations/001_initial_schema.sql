-- Garcar Enterprise — Supabase Initial Schema
-- Run via: supabase db push

-- Tenants table (one row per paying customer)
CREATE TABLE IF NOT EXISTS tenants (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               TEXT NOT NULL UNIQUE,
    name                TEXT,
    stripe_customer_id  TEXT,
    product             TEXT,
    amount_paid         NUMERIC(10,2),
    status              TEXT DEFAULT 'active' CHECK (status IN ('active','suspended','churned')),
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- Audit events table
CREATE TABLE IF NOT EXISTS audit_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT,                          -- 'system' for platform-level events
    event_type  TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Prospects table (Hunter.io seeded)
CREATE TABLE IF NOT EXISTS prospects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL UNIQUE,
    first_name  TEXT,
    last_name   TEXT,
    domain      TEXT,
    position    TEXT,
    confidence  INTEGER,
    status      TEXT DEFAULT 'new' CHECK (status IN ('new','contacted','qualified','converted','dead')),
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Row Level Security
ALTER TABLE tenants       ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events  ENABLE ROW LEVEL SECURITY;
ALTER TABLE prospects     ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS (used by backend)
-- Tenant-facing roles should use per-tenant policies
CREATE POLICY "Service role full access" ON tenants
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role full access" ON audit_events
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Service role full access" ON prospects
    FOR ALL USING (auth.role() = 'service_role');

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tenants_email        ON tenants(email);
CREATE INDEX IF NOT EXISTS idx_tenants_stripe       ON tenants(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_audit_tenant         ON audit_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_event_type     ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_prospects_status     ON prospects(status);
CREATE INDEX IF NOT EXISTS idx_prospects_domain     ON prospects(domain);
