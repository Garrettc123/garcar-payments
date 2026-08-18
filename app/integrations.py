from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.settings import get_settings

logger = logging.getLogger("garcar.integrations")


class IntegrationError(RuntimeError):
    def __init__(self, system: str, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.system = system
        self.retryable = retryable


def _request(system: str, method: str, url: str, *, headers: dict[str, str], body: Any | None = None, timeout: int = 10) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:2000]
        retryable = exc.code == 429 or exc.code >= 500
        raise IntegrationError(system, f"HTTP {exc.code}: {raw}", retryable=retryable) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise IntegrationError(system, f"network failure: {type(exc).__name__}") from exc


@dataclass(frozen=True)
class HubSpotContact:
    id: str
    email: str | None


def hubspot_find_contact(stripe_customer_id: str, email: str) -> HubSpotContact | None:
    s = get_settings()
    if not s.hubspot_access_token:
        raise IntegrationError("hubspot", "HUBSPOT_ACCESS_TOKEN is not configured", retryable=False)
    url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
    headers = {"Authorization": f"Bearer {s.hubspot_access_token}", "Content-Type": "application/json"}
    # Prefer the Stripe customer ID, then fall back to email. The Stripe ID
    # property must exist in HubSpot as stripe_customer_id for the first query.
    body = {
        "filterGroups": [{"filters": [{"propertyName": "stripe_customer_id", "operator": "EQ", "value": stripe_customer_id}]}],
        "properties": ["email", "stripe_customer_id"],
        "limit": 1,
    }
    result = _request("hubspot", "POST", url, headers=headers, body=body)
    if result.get("results"):
        obj = result["results"][0]
        return HubSpotContact(obj["id"], (obj.get("properties") or {}).get("email"))

    # Email fallback makes existing contacts usable before the custom property
    # has been populated. The caller then upserts the Stripe ID.
    body["filterGroups"] = [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}]
    result = _request("hubspot", "POST", url, headers=headers, body=body)
    if result.get("results"):
        obj = result["results"][0]
        return HubSpotContact(obj["id"], (obj.get("properties") or {}).get("email"))
    return None


def hubspot_link_contact(contact_id: str, stripe_customer_id: str) -> None:
    s = get_settings()
    if not s.hubspot_access_token:
        raise IntegrationError("hubspot", "HUBSPOT_ACCESS_TOKEN is not configured", retryable=False)
    _request(
        "hubspot", "PATCH", f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}",
        headers={"Authorization": f"Bearer {s.hubspot_access_token}", "Content-Type": "application/json"},
        body={"properties": {"stripe_customer_id": stripe_customer_id}},
    )


def supabase_upsert_entitlement(*, stripe_event_id: str, checkout_session_id: str, stripe_customer_id: str, hubspot_contact_id: str, plan: str, email: str) -> dict[str, Any]:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_key:
        raise IntegrationError("supabase", "SUPABASE_URL/SUPABASE_SERVICE_KEY are not configured", retryable=False)
    row = {
        "stripe_event_id": stripe_event_id,
        "checkout_session_id": checkout_session_id,
        "stripe_customer_id": stripe_customer_id,
        "hubspot_contact_id": hubspot_contact_id,
        "plan": plan,
        "customer_email": email,
        "status": "active",
    }
    return _request(
        "supabase", "POST", f"{s.supabase_url.rstrip('/')}/rest/v1/garcar_entitlements?on_conflict=checkout_session_id",
        headers={"apikey": s.supabase_service_key, "Authorization": f"Bearer {s.supabase_service_key}", "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=representation"},
        body=row,
    )


def asana_create_onboarding(*, checkout_session_id: str, customer_email: str, plan: str) -> dict[str, Any]:
    s = get_settings()
    if not s.asana_access_token or not s.asana_workspace_gid:
        raise IntegrationError("asana", "ASANA_ACCESS_TOKEN/ASANA_WORKSPACE_GID are not configured", retryable=False)
    headers = {"Authorization": f"Bearer {s.asana_access_token}", "Content-Type": "application/json"}
    project = _request(
        "asana", "POST", "https://app.asana.com/api/1.0/projects", headers=headers,
        body={"data": {"name": f"Onboarding — {customer_email} — {plan}", "workspace": s.asana_workspace_gid, "notes": f"Stripe checkout session: {checkout_session_id}"}},
    )
    project_gid = project.get("data", {}).get("gid")
    if not project_gid:
        raise IntegrationError("asana", "Asana did not return a project GID")
    task = _request(
        "asana", "POST", "https://app.asana.com/api/1.0/tasks", headers=headers,
        body={"data": {"name": f"Complete onboarding — {customer_email}", "projects": [project_gid], "notes": f"Plan: {plan}\nStripe checkout session: {checkout_session_id}"}},
    )
    return {"project_id": project_gid, "task_id": task.get("data", {}).get("gid")}


def notion_log_event(*, event_id: str, checkout_session_id: str, stripe_customer_id: str, hubspot_contact_id: str, plan: str, status: str = "completed") -> dict[str, Any]:
    s = get_settings()
    if not s.notion_token or not s.notion_revenue_db_id:
        raise IntegrationError("notion", "NOTION_TOKEN/NOTION_REVENUE_DB_ID are not configured", retryable=False)
    headers = {"Authorization": f"Bearer {s.notion_token}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    properties = {
        "Name": {"title": [{"text": {"content": f"Checkout {checkout_session_id}"}}]},
        "Event ID": {"rich_text": [{"text": {"content": event_id}}]},
        "Status": {"select": {"name": status}},
        "Plan": {"rich_text": [{"text": {"content": plan}}]},
        "Stripe Customer ID": {"rich_text": [{"text": {"content": stripe_customer_id}}]},
        "HubSpot Contact ID": {"rich_text": [{"text": {"content": hubspot_contact_id}}]},
    }
    return _request("notion", "POST", "https://api.notion.com/v1/pages", headers=headers, body={"parent": {"database_id": s.notion_revenue_db_id}, "properties": properties})


def linear_create_incident(*, correlation_id: str, failed_stage: str, error: str, attempts: int) -> str | None:
    s = get_settings()
    if not s.linear_api_key or not s.linear_team_id:
        logger.error("Linear incident could not be created: Linear credentials are not configured")
        return None
    query = "mutation CreateIssue($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier } } }"
    body = {"query": query, "variables": {"input": {"teamId": s.linear_team_id, "title": f"Checkout orchestration failure: {failed_stage}", "description": f"Correlation ID: {correlation_id}\nFailed stage: {failed_stage}\nAttempts: {attempts}\nError: {error[:4000]}"}}}
    result = _request("linear", "POST", "https://api.linear.app/graphql", headers={"Authorization": s.linear_api_key, "Content-Type": "application/json"}, body=body)
    return (((result.get("data") or {}).get("issueCreate") or {}).get("issue") or {}).get("identifier")
