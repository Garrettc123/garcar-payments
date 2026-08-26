"""Notion — client workspace creation and ops log writes."""
import httpx
import logging
from datetime import datetime, timezone
from integrations.config import Config

logger = logging.getLogger(__name__)
NOTION_API = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {Config.NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}


def create_client_workspace(name: str, email: str, product: str,
                             linear_project_id: str, tenant_id: str) -> str:
    """Create a Notion page in the Clients database. Returns page ID."""
    payload = {
        "parent": {"database_id": Config.NOTION_CLIENTS_DB},
        "properties": {
            "Name":          {"title": [{"text": {"content": name}}]},
            "Email":         {"email": email},
            "Product":       {"select": {"name": product}},
            "Status":        {"select": {"name": "Onboarding"}},
            "Linear Project":{"rich_text": [{"text": {"content": linear_project_id}}]},
            "Tenant ID":     {"rich_text": [{"text": {"content": tenant_id}}]},
            "Activation Date": {"date": {"start": datetime.now(timezone.utc).date().isoformat()}}
        }
    }
    r = httpx.post(f"{NOTION_API}/pages", json=payload, headers=HEADERS)
    if r.status_code not in (200, 201):
        logger.error(f"Notion workspace creation failed: {r.text}")
        r.raise_for_status()
    page_id = r.json()["id"]
    logger.info(f"Notion client workspace created: {page_id} — {name}")
    return page_id


def append_ops_log(message: str, level: str = "INFO"):
    """Append a timestamped log entry to the Notion ops page."""
    if not Config.NOTION_OPS_PAGE:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    block = {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{
                "type": "text",
                "text": {"content": f"[{level}] {ts} — {message}"}
            }]
        }
    }
    r = httpx.patch(
        f"{NOTION_API}/blocks/{Config.NOTION_OPS_PAGE}/children",
        json={"children": [block]},
        headers=HEADERS
    )
    if r.status_code not in (200, 201):
        logger.warning(f"Notion ops log append failed: {r.text}")
