"""Supabase — tenant provisioning and ledger writes."""
import httpx
import logging
import uuid
from datetime import datetime, timezone
from integrations.config import Config

logger = logging.getLogger(__name__)


def _headers():
    return {
        "apikey": Config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {Config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


def provision_tenant(email: str, name: str, stripe_customer_id: str,
                     product: str, amount: float) -> str:
    """Insert a tenant row. Returns tenant_id (UUID)."""
    tenant_id = str(uuid.uuid4())
    row = {
        "id": tenant_id,
        "email": email,
        "name": name,
        "stripe_customer_id": stripe_customer_id,
        "product": product,
        "amount_paid": amount,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    url = f"{Config.SUPABASE_URL}/rest/v1/tenants"
    r = httpx.post(url, json=row, headers=_headers())
    if r.status_code not in (200, 201):
        logger.error(f"Supabase tenant provision failed: {r.text}")
        r.raise_for_status()
    logger.info(f"Supabase tenant provisioned: {tenant_id} — {email}")
    return tenant_id


def log_event(tenant_id: str, event_type: str, metadata: dict):
    """Append to the audit ledger."""
    row = {
        "tenant_id": tenant_id,
        "event_type": event_type,
        "metadata": metadata,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    url = f"{Config.SUPABASE_URL}/rest/v1/audit_events"
    r = httpx.post(url, json=row, headers=_headers())
    if r.status_code not in (200, 201):
        logger.warning(f"Supabase audit log failed: {r.text}")


def get_tenant(email: str) -> dict | None:
    """Fetch tenant row by email."""
    url = f"{Config.SUPABASE_URL}/rest/v1/tenants?email=eq.{email}&limit=1"
    r = httpx.get(url, headers=_headers())
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


def update_tenant_status(tenant_id: str, status: str):
    """Update tenant status (active / suspended / churned)."""
    url = f"{Config.SUPABASE_URL}/rest/v1/tenants?id=eq.{tenant_id}"
    r = httpx.patch(url, json={"status": status}, headers=_headers())
    r.raise_for_status()
    logger.info(f"Tenant {tenant_id} status → {status}")
