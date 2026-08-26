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


def _request(system: str, method: str, url: str, *, headers: dict[str, str], body: Any | None = None,
             timeout: int = 10, operation_key: str | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    merged = {"Accept": "application/json", **headers}
    if operation_key:
        # Providers that support idempotency can honor this; reconciliation
        # logic below protects providers that do not.
        merged.setdefault("Idempotency-Key", operation_key)
        merged.setdefault("X-Garcar-Operation-Key", operation_key)
    req = urllib.request.Request(url, data=data, method=method, headers=merged)
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
    body = {"filterGroups": [{"filters": [{"propertyName": "stripe_customer_id", "operator": "EQ", "value": stripe_customer_id}]}], "properties": ["email", "stripe_customer_id"], "limit": 1}
    result = _request("hubspot", "POST", url, headers=headers, body=body, operation_key=f"hubspot-match:{stripe_customer_id}")
    if result.get("results"):
        obj = result["results"][0]
        return HubSpotContact(obj["id"], (obj.get("properties") or {}).get("email"))
    body["filterGroups"] = [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}]
    result = _request("hubspot", "POST", url, headers=headers, body=body, operation_key=f"hubspot-match-email:{email.lower()}")
    if result.get("results"):
        obj = result["results"][0]
        return HubSpotContact(obj["id"], (obj.get("properties") or {}).get("email"))
    return None


def hubspot_link_contact(contact_id: str, stripe_customer_id: str) -> None:
    s = get_settings()
    if not s.hubspot_access_token:
        raise IntegrationError("hubspot", "HUBSPOT_ACCESS_TOKEN is not configured", retryable=False)
    _request("hubspot", "PATCH", f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}",
             headers={"Authorization": f"Bearer {s.hubspot_access_token}", "Content-Type": "application/json"},
             body={"properties": {"stripe_customer_id": stripe_customer_id}}, operation_key=f"hubspot-link:{contact_id}:{stripe_customer_id}")


def supabase_upsert_entitlement(*, stripe_event_id: str, checkout_session_id: str, stripe_customer_id: str,
                                hubspot_contact_id: str, plan: str, email: str) -> dict[str, Any]:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_key:
        raise IntegrationError("supabase", "SUPABASE_URL/SUPABASE_SERVICE_KEY are not configured", retryable=False)
    row = {"stripe_event_id": stripe_event_id, "checkout_session_id": checkout_session_id, "stripe_customer_id": stripe_customer_id,
           "hubspot_contact_id": hubspot_contact_id, "plan": plan, "customer_email": email, "status": "active"}
    return _request("supabase", "POST", f"{s.supabase_url.rstrip('/')}/rest/v1/garcar_entitlements?on_conflict=checkout_session_id",
                    headers={"apikey": s.supabase_service_key, "Authorization": f"Bearer {s.supabase_service_key}", "Content-Type": "application/json",
                             "Prefer": "resolution=merge-duplicates,return=representation"}, body=row, operation_key=f"supabase-entitlement:{checkout_session_id}")


def asana_create_onboarding(*, checkout_session_id: str, customer_email: str, plan: str) -> dict[str, Any]:
    s = get_settings()
    if not s.asana_access_token or not s.asana_workspace_gid:
        raise IntegrationError("asana", "ASANA_ACCESS_TOKEN/ASANA_WORKSPACE_GID are not configured", retryable=False)
    headers = {"Authorization": f"Bearer {s.asana_access_token}", "Content-Type": "application/json"}
    project_name = f"Onboarding — {customer_email} — {plan}"
    # Reconcile first: Asana does not provide a universal create-idempotency
    # guarantee, so the deterministic project name is the durable operation key.
    projects = _request("asana", "GET", f"https://app.asana.com/api/1.0/projects?workspace={s.asana_workspace_gid}&archived=false&limit=100",
                        headers=headers, operation_key=f"asana-project:{checkout_session_id}")
    project_obj = next((p for p in projects.get("data", []) if p.get("name") == project_name), None)
    if project_obj is None:
        project = _request("asana", "POST", "https://app.asana.com/api/1.0/projects", headers=headers,
                           body={"data": {"name": project_name, "workspace": s.asana_workspace_gid, "notes": f"Stripe checkout session: {checkout_session_id}"}},
                           operation_key=f"asana-project:{checkout_session_id}")
        project_obj = project.get("data") or {}
    project_gid = project_obj.get("gid")
    if not project_gid:
        raise IntegrationError("asana", "Asana did not return a project GID")

    task_name = f"Complete onboarding — {customer_email}"
    tasks = _request("asana", "GET", f"https://app.asana.com/api/1.0/tasks?project={project_gid}&completed_since=now&limit=100",
                      headers=headers, operation_key=f"asana-task:{checkout_session_id}")
    task_obj = next((t for t in tasks.get("data", []) if t.get("name") == task_name), None)
    if task_obj is None:
        task = _request("asana", "POST", "https://app.asana.com/api/1.0/tasks", headers=headers,
                        body={"data": {"name": task_name, "projects": [project_gid], "notes": f"Plan: {plan}\nStripe checkout session: {checkout_session_id}"}},
                        operation_key=f"asana-task:{checkout_session_id}")
        task_obj = task.get("data") or {}
    return {"project_id": project_gid, "task_id": task_obj.get("gid")}


def notion_log_event(*, event_id: str, checkout_session_id: str, stripe_customer_id: str,
                     hubspot_contact_id: str, plan: str, status: str = "completed") -> dict[str, Any]:
    s = get_settings()
    if not s.notion_token or not s.notion_revenue_db_id:
        raise IntegrationError("notion", "NOTION_TOKEN/NOTION_REVENUE_DB_ID are not configured", retryable=False)
    headers = {"Authorization": f"Bearer {s.notion_token}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    # Reconcile an existing audit page by immutable Stripe event ID before create.
    try:
        existing = _request("notion", "POST", f"https://api.notion.com/v1/databases/{s.notion_revenue_db_id}/query", headers=headers,
                            body={"filter": {"property": "Event ID", "rich_text": {"equals": event_id}}, "page_size": 1},
                            operation_key=f"notion-query:{event_id}")
        if existing.get("results"):
            return existing["results"][0]
    except IntegrationError as exc:
        if not exc.retryable:
            raise
        logger.warning("Notion reconciliation query failed; create will be attempted: %s", exc)

    properties = {
        "Name": {"title": [{"text": {"content": f"Checkout {checkout_session_id}"}}]},
        "Event ID": {"rich_text": [{"text": {"content": event_id}}]},
        "Status": {"select": {"name": status}},
        "Plan": {"rich_text": [{"text": {"content": plan}}]},
        "Stripe Customer ID": {"rich_text": [{"text": {"content": stripe_customer_id}}]},
        "HubSpot Contact ID": {"rich_text": [{"text": {"content": hubspot_contact_id}}]},
    }
    return _request("notion", "POST", "https://api.notion.com/v1/pages", headers=headers,
                    body={"parent": {"database_id": s.notion_revenue_db_id}, "properties": properties}, operation_key=f"notion-event:{event_id}")


def linear_create_incident(*, correlation_id: str, failed_stage: str, error: str, attempts: int) -> str | None:
    s = get_settings()
    if not s.linear_api_key or not s.linear_team_id:
        logger.error("Linear incident could not be created: Linear credentials are not configured")
        return None
    query = "mutation CreateIssue($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier } } }"
    body = {"query": query, "variables": {"input": {"teamId": s.linear_team_id, "title": f"Checkout orchestration failure: {failed_stage}", "description": f"Correlation ID: {correlation_id}\nFailed stage: {failed_stage}\nAttempts: {attempts}\nError: {error[:4000]}"}}}
    result = _request("linear", "POST", "https://api.linear.app/graphql", headers={"Authorization": s.linear_api_key, "Content-Type": "application/json"}, body=body, operation_key=f"linear-incident:{correlation_id}:{failed_stage}")
    return (((result.get("data") or {}).get("issueCreate") or {}).get("issue") or {}).get("identifier")
