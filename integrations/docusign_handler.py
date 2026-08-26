"""DocuSign — auto-send service agreements on purchase."""
import httpx
import logging
from integrations.config import Config

logger = logging.getLogger(__name__)

DS_BASE = "https://na4.docusign.net/restapi/v2.1"


def send_contract(email: str, name: str, product: str, amount: float) -> str:
    """Send the appropriate DocuSign template based on product. Returns envelope ID."""
    template_id = _select_template(product)
    payload = {
        "templateId": template_id,
        "templateRoles": [{
            "email": email,
            "name": name,
            "roleName": "Client",
            "tabs": {
                "textTabs": [
                    {"tabLabel": "ProductName", "value": product},
                    {"tabLabel": "ContractAmount", "value": f"${amount:,.2f}"}
                ]
            }
        }],
        "status": "sent",
        "emailSubject": f"Garcar Enterprise — Your {product} Service Agreement",
        "emailBlurb": (
            f"Dear {name},\n\nPlease review and sign your {product} service agreement. "
            "This establishes the terms of our engagement.\n\nGarcar Enterprise"
        )
    }
    headers = {
        "Authorization": f"Bearer {Config.DOCUSIGN_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    url = f"{DS_BASE}/accounts/{Config.DOCUSIGN_ACCOUNT_ID}/envelopes"
    r = httpx.post(url, json=payload, headers=headers)
    if r.status_code not in (200, 201):
        logger.error(f"DocuSign envelope failed: {r.text}")
        r.raise_for_status()
    envelope_id = r.json()["envelopeId"]
    logger.info(f"DocuSign envelope sent: {envelope_id} → {email}")
    return envelope_id


def _select_template(product: str) -> str:
    """Map product name to DocuSign template ID."""
    product_lower = product.lower()
    if "iras" in product_lower:
        return Config.DOCUSIGN_TEMPLATE_IRAS
    if "operator fabric" in product_lower or "opf" in product_lower:
        return Config.DOCUSIGN_TEMPLATE_OPF
    # Default to IRAS template
    return Config.DOCUSIGN_TEMPLATE_IRAS


def get_envelope_status(envelope_id: str) -> str:
    """Check status of a sent envelope."""
    headers = {"Authorization": f"Bearer {Config.DOCUSIGN_ACCESS_TOKEN}"}
    url = f"{DS_BASE}/accounts/{Config.DOCUSIGN_ACCOUNT_ID}/envelopes/{envelope_id}"
    r = httpx.get(url, headers=headers)
    r.raise_for_status()
    return r.json().get("status", "unknown")
