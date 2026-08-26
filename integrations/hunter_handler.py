"""Hunter.io — domain search and email verification for IRAS prospecting."""
import httpx
import logging
from integrations.config import Config

logger = logging.getLogger(__name__)
HUNTER_BASE = "https://api.hunter.io/v2"


def domain_search(domain: str, limit: int = 10) -> list[dict]:
    """Return up to `limit` verified contacts for a domain."""
    r = httpx.get(
        f"{HUNTER_BASE}/domain-search",
        params={"domain": domain, "limit": limit, "api_key": Config.HUNTER_API_KEY}
    )
    r.raise_for_status()
    data = r.json().get("data", {})
    emails = data.get("emails", [])
    logger.info(f"Hunter domain search: {domain} → {len(emails)} contacts")
    return emails


def verify_email(email: str) -> dict:
    """Verify a single email address. Returns result dict."""
    r = httpx.get(
        f"{HUNTER_BASE}/email-verifier",
        params={"email": email, "api_key": Config.HUNTER_API_KEY}
    )
    r.raise_for_status()
    result = r.json().get("data", {})
    status = result.get("status", "unknown")
    logger.info(f"Hunter email verify: {email} → {status}")
    return result


def seed_prospect_queue(domains: list[str], supabase_handler) -> int:
    """Search each domain, verify emails, insert verified contacts into Supabase prospects table."""
    inserted = 0
    for domain in domains:
        contacts = domain_search(domain, limit=5)
        for c in contacts:
            email = c.get("value")
            if not email:
                continue
            verified = verify_email(email)
            if verified.get("status") in ("valid", "webmail"):
                supabase_handler.log_event(
                    tenant_id="system",
                    event_type="prospect_added",
                    metadata={
                        "email": email,
                        "domain": domain,
                        "first_name": c.get("first_name"),
                        "last_name": c.get("last_name"),
                        "position": c.get("position"),
                        "confidence": c.get("confidence"),
                        "hunter_status": verified.get("status")
                    }
                )
                inserted += 1
    logger.info(f"Prospect queue seeded: {inserted} contacts from {len(domains)} domains")
    return inserted
