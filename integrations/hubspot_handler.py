"""HubSpot CRM — contact and deal management."""
import requests
import logging
from integrations.config import Config

logger = logging.getLogger(__name__)
BASE_URL = "https://api.hubapi.com"
HEADERS = {
    "Authorization": f"Bearer {Config.HUBSPOT_TOKEN}",
    "Content-Type": "application/json"
}


def upsert_contact(email: str, name: str, source: str = "garcar-system") -> str:
    """Create or update a HubSpot contact. Returns contact ID."""
    first, *last = name.split(" ", 1)
    payload = {
        "properties": {
            "email": email,
            "firstname": first,
            "lastname": last[0] if last else "",
            "hs_lead_status": "NEW",
            "lead_source": source
        }
    }
    # Try create first, fall back to update on conflict
    r = requests.post(f"{BASE_URL}/crm/v3/objects/contacts", json=payload, headers=HEADERS)
    if r.status_code == 409:  # conflict — contact exists
        contact_id = r.json()["message"].split("ID: ")[-1]
        requests.patch(f"{BASE_URL}/crm/v3/objects/contacts/{contact_id}",
                       json=payload, headers=HEADERS)
        return contact_id
    r.raise_for_status()
    contact_id = r.json()["id"]
    logger.info(f"HubSpot contact upserted: {email} → {contact_id}")
    return contact_id


def create_deal(email: str, name: str, amount: float, product: str) -> str:
    """Create a deal in the IRAS pipeline. Returns deal ID."""
    contact_id = upsert_contact(email, name)
    payload = {
        "properties": {
            "dealname": f"{name} — {product}",
            "amount": str(amount),
            "pipeline": Config.HUBSPOT_PIPELINE_ID,
            "dealstage": Config.HUBSPOT_STAGE_NEW,
            "closedate": None
        }
    }
    r = requests.post(f"{BASE_URL}/crm/v3/objects/deals", json=payload, headers=HEADERS)
    r.raise_for_status()
    deal_id = r.json()["id"]
    # Associate deal ↔ contact
    assoc = [{"to": {"id": contact_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 3}]}]
    requests.put(f"{BASE_URL}/crm/v4/objects/deals/{deal_id}/associations/contacts/batch/create",
                 json={"inputs": assoc}, headers=HEADERS)
    logger.info(f"HubSpot deal created: {deal_id} — {name} ${amount}")
    return deal_id


def close_deal(email: str, name: str, amount: float, product: str) -> str:
    """Create deal and immediately mark closed-won."""
    deal_id = create_deal(email, name, amount, product)
    requests.patch(
        f"{BASE_URL}/crm/v3/objects/deals/{deal_id}",
        json={"properties": {"dealstage": Config.HUBSPOT_STAGE_CLOSED}},
        headers=HEADERS
    ).raise_for_status()
    logger.info(f"HubSpot deal closed-won: {deal_id}")
    return deal_id


def enroll_sequence(contact_id: str, sequence_id: str):
    """Enroll a contact in a HubSpot email sequence."""
    payload = {"contactId": contact_id, "sequenceId": sequence_id}
    r = requests.post(f"{BASE_URL}/automation/v4/sequences/enrollments",
                      json=payload, headers=HEADERS)
    if r.status_code not in (200, 201, 204):
        logger.warning(f"Sequence enrollment failed: {r.text}")
    return r.status_code
