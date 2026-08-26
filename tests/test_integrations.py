"""
Tests for app/integrations.py — CRM onboarding integrations.

All external HTTP calls are intercepted by patching urllib.request.urlopen
so no real network traffic is made.
"""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from app.integrations import (
    HubSpotContact,
    IntegrationError,
    asana_create_onboarding,
    hubspot_find_contact,
    hubspot_link_contact,
    linear_create_incident,
    notion_log_event,
    supabase_upsert_entitlement,
)
from app.settings import Settings


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fake_response(body: dict | list, status: int = 200):
    """Return a mock context-manager response that urlopen can yield."""
    raw = json.dumps(body).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


def _http_error(code: int, body: str = "error") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example.com",
        code=code,
        msg="error",
        hdrs=MagicMock(),
        fp=io.BytesIO(body.encode("utf-8")),
    )


def _settings(**kwargs) -> Settings:
    defaults = dict(
        hubspot_access_token="hb_tok",
        supabase_url="https://supabase.example.com",
        supabase_service_key="sb_svc_key",
        asana_access_token="asana_tok",
        asana_workspace_gid="ws_gid_123",
        notion_token="notion_tok",
        notion_revenue_db_id="db_123",
        linear_api_key="lin_key",
        linear_team_id="team_id",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


# ── IntegrationError ─────────────────────────────────────────────────────────

def test_integration_error_stores_system_and_retryable():
    err = IntegrationError("hubspot", "something failed", retryable=False)
    assert err.system == "hubspot"
    assert err.retryable is False
    assert "something failed" in str(err)


def test_integration_error_defaults_retryable_true():
    err = IntegrationError("supabase", "timeout")
    assert err.retryable is True


# ── _request (via hubspot_find_contact as a convenient driver) ───────────────

def test_request_raises_integration_error_on_http_4xx():
    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", side_effect=_http_error(403, "forbidden")):
            with pytest.raises(IntegrationError) as exc_info:
                hubspot_find_contact("cus_123", "a@b.com")
    assert "HTTP 403" in str(exc_info.value)
    assert exc_info.value.retryable is False  # 4xx (not 429) is not retryable


def test_request_raises_retryable_on_http_429():
    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", side_effect=_http_error(429, "rate limited")):
            with pytest.raises(IntegrationError) as exc_info:
                hubspot_find_contact("cus_123", "a@b.com")
    assert exc_info.value.retryable is True


def test_request_raises_retryable_on_http_5xx():
    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", side_effect=_http_error(503, "service unavailable")):
            with pytest.raises(IntegrationError) as exc_info:
                hubspot_find_contact("cus_123", "a@b.com")
    assert exc_info.value.retryable is True


def test_request_raises_on_network_failure():
    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            with pytest.raises(IntegrationError) as exc_info:
                hubspot_find_contact("cus_123", "a@b.com")
    assert "network failure" in str(exc_info.value)
    assert exc_info.value.retryable is True


# ── hubspot_find_contact ──────────────────────────────────────────────────────

def test_hubspot_find_contact_found_by_stripe_id():
    results_payload = {"results": [{"id": "hs_001", "properties": {"email": "a@b.com"}}]}
    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", return_value=_fake_response(results_payload)):
            contact = hubspot_find_contact("cus_123", "a@b.com")
    assert contact == HubSpotContact("hs_001", "a@b.com")


def test_hubspot_find_contact_fallback_to_email():
    """First query (by Stripe ID) returns nothing; second query (by email) finds contact."""
    no_results = {"results": []}
    found = {"results": [{"id": "hs_002", "properties": {"email": "x@y.com"}}]}

    call_count = 0

    def _urlopen(req, timeout=10):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _fake_response(no_results)
        return _fake_response(found)

    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", side_effect=_urlopen):
            contact = hubspot_find_contact("cus_missing", "x@y.com")
    assert contact == HubSpotContact("hs_002", "x@y.com")
    assert call_count == 2


def test_hubspot_find_contact_returns_none_when_not_found():
    no_results = {"results": []}
    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", return_value=_fake_response(no_results)):
            contact = hubspot_find_contact("cus_ghost", "ghost@example.com")
    assert contact is None


def test_hubspot_find_contact_raises_when_token_missing():
    with patch("app.integrations.get_settings", return_value=_settings(hubspot_access_token="")):
        with pytest.raises(IntegrationError) as exc_info:
            hubspot_find_contact("cus_123", "a@b.com")
    assert exc_info.value.system == "hubspot"
    assert exc_info.value.retryable is False


# ── hubspot_link_contact ──────────────────────────────────────────────────────

def test_hubspot_link_contact_success():
    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", return_value=_fake_response({})):
            hubspot_link_contact("hs_001", "cus_123")  # no exception = success


def test_hubspot_link_contact_raises_when_token_missing():
    with patch("app.integrations.get_settings", return_value=_settings(hubspot_access_token="")):
        with pytest.raises(IntegrationError) as exc_info:
            hubspot_link_contact("hs_001", "cus_123")
    assert exc_info.value.retryable is False


# ── supabase_upsert_entitlement ───────────────────────────────────────────────

def test_supabase_upsert_entitlement_success():
    response_data = [{"id": "row_1", "status": "active"}]
    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", return_value=_fake_response(response_data)):
            result = supabase_upsert_entitlement(
                stripe_event_id="evt_001",
                checkout_session_id="cs_001",
                stripe_customer_id="cus_001",
                hubspot_contact_id="hs_001",
                plan="audit",
                email="buyer@example.com",
            )
    assert result == response_data


def test_supabase_upsert_entitlement_raises_when_not_configured():
    with patch("app.integrations.get_settings", return_value=_settings(supabase_url="")):
        with pytest.raises(IntegrationError) as exc_info:
            supabase_upsert_entitlement(
                stripe_event_id="evt_001",
                checkout_session_id="cs_001",
                stripe_customer_id="cus_001",
                hubspot_contact_id="hs_001",
                plan="audit",
                email="buyer@example.com",
            )
    assert exc_info.value.system == "supabase"
    assert exc_info.value.retryable is False


# ── asana_create_onboarding ───────────────────────────────────────────────────

def test_asana_create_onboarding_creates_project_and_task():
    """Both project and task are absent — both POST calls must be made."""
    project_name = "Onboarding — buyer@example.com — audit"
    task_name = "Complete onboarding — buyer@example.com"
    call_count = 0

    def _urlopen(req, timeout=10):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # GET projects list — empty
            return _fake_response({"data": []})
        if call_count == 2:
            # POST create project
            return _fake_response({"data": {"gid": "proj_gid_001", "name": project_name}})
        if call_count == 3:
            # GET tasks list — empty
            return _fake_response({"data": []})
        # POST create task
        return _fake_response({"data": {"gid": "task_gid_001", "name": task_name}})

    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", side_effect=_urlopen):
            result = asana_create_onboarding(
                checkout_session_id="cs_001",
                customer_email="buyer@example.com",
                plan="audit",
            )
    assert result["project_id"] == "proj_gid_001"
    assert result["task_id"] == "task_gid_001"
    assert call_count == 4


def test_asana_create_onboarding_idempotent_when_project_and_task_exist():
    """Existing project and task are reused without additional POSTs."""
    project_name = "Onboarding — buyer@example.com — audit"
    task_name = "Complete onboarding — buyer@example.com"
    call_count = 0

    def _urlopen(req, timeout=10):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _fake_response({"data": [{"gid": "proj_existing", "name": project_name}]})
        # GET tasks list — task already exists
        return _fake_response({"data": [{"gid": "task_existing", "name": task_name}]})

    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", side_effect=_urlopen):
            result = asana_create_onboarding(
                checkout_session_id="cs_001",
                customer_email="buyer@example.com",
                plan="audit",
            )
    assert result["project_id"] == "proj_existing"
    assert result["task_id"] == "task_existing"
    assert call_count == 2  # only the two GET calls, no POSTs


def test_asana_create_onboarding_raises_when_not_configured():
    with patch("app.integrations.get_settings", return_value=_settings(asana_access_token="")):
        with pytest.raises(IntegrationError) as exc_info:
            asana_create_onboarding(
                checkout_session_id="cs_001",
                customer_email="buyer@example.com",
                plan="audit",
            )
    assert exc_info.value.system == "asana"
    assert exc_info.value.retryable is False


def test_asana_create_onboarding_raises_when_no_project_gid_returned():
    call_count = 0

    def _urlopen(req, timeout=10):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _fake_response({"data": []})
        # POST create project returns no gid
        return _fake_response({"data": {}})

    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", side_effect=_urlopen):
            with pytest.raises(IntegrationError) as exc_info:
                asana_create_onboarding(
                    checkout_session_id="cs_001",
                    customer_email="buyer@example.com",
                    plan="audit",
                )
    assert "project GID" in str(exc_info.value)


# ── notion_log_event ──────────────────────────────────────────────────────────

def test_notion_log_event_returns_existing_page_without_create():
    existing_page = {"id": "page_001", "properties": {}}
    call_count = 0

    def _urlopen(req, timeout=10):
        nonlocal call_count
        call_count += 1
        # First call: database query — page found
        return _fake_response({"results": [existing_page]})

    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", side_effect=_urlopen):
            result = notion_log_event(
                event_id="evt_001",
                checkout_session_id="cs_001",
                stripe_customer_id="cus_001",
                hubspot_contact_id="hs_001",
                plan="audit",
            )
    assert result == existing_page
    assert call_count == 1  # only the query, no create


def test_notion_log_event_creates_page_when_not_found():
    call_count = 0
    new_page = {"id": "page_new", "properties": {}}

    def _urlopen(req, timeout=10):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _fake_response({"results": []})
        return _fake_response(new_page)

    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", side_effect=_urlopen):
            result = notion_log_event(
                event_id="evt_new",
                checkout_session_id="cs_001",
                stripe_customer_id="cus_001",
                hubspot_contact_id="hs_001",
                plan="audit",
            )
    assert result == new_page
    assert call_count == 2


def test_notion_log_event_falls_through_to_create_on_retryable_query_error():
    """If the reconciliation query fails with a retryable error, creation is attempted."""
    new_page = {"id": "page_fallback", "properties": {}}
    call_count = 0

    def _urlopen(req, timeout=10):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise urllib.error.HTTPError(
                url="https://api.notion.com/v1/databases/db_123/query",
                code=503,
                msg="service unavailable",
                hdrs=MagicMock(),
                fp=io.BytesIO(b"unavailable"),
            )
        return _fake_response(new_page)

    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", side_effect=_urlopen):
            result = notion_log_event(
                event_id="evt_fallback",
                checkout_session_id="cs_001",
                stripe_customer_id="cus_001",
                hubspot_contact_id="hs_001",
                plan="audit",
            )
    assert result == new_page
    assert call_count == 2


def test_notion_log_event_raises_when_not_configured():
    with patch("app.integrations.get_settings", return_value=_settings(notion_token="")):
        with pytest.raises(IntegrationError) as exc_info:
            notion_log_event(
                event_id="evt_001",
                checkout_session_id="cs_001",
                stripe_customer_id="cus_001",
                hubspot_contact_id="hs_001",
                plan="audit",
            )
    assert exc_info.value.system == "notion"
    assert exc_info.value.retryable is False


# ── linear_create_incident ────────────────────────────────────────────────────

def test_linear_create_incident_returns_identifier():
    response = {"data": {"issueCreate": {"success": True, "issue": {"id": "abc", "identifier": "ENG-42"}}}}
    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", return_value=_fake_response(response)):
            identifier = linear_create_incident(
                correlation_id="corr_001",
                failed_stage="hubspot",
                error="timeout",
                attempts=3,
            )
    assert identifier == "ENG-42"


def test_linear_create_incident_returns_none_when_not_configured():
    with patch("app.integrations.get_settings", return_value=_settings(linear_api_key="")):
        result = linear_create_incident(
            correlation_id="corr_001",
            failed_stage="hubspot",
            error="timeout",
            attempts=3,
        )
    assert result is None


def test_linear_create_incident_returns_none_when_response_missing_identifier():
    response = {"data": {"issueCreate": {"success": False, "issue": None}}}
    with patch("app.integrations.get_settings", return_value=_settings()):
        with patch("urllib.request.urlopen", return_value=_fake_response(response)):
            result = linear_create_incident(
                correlation_id="corr_001",
                failed_stage="notion",
                error="bad gateway",
                attempts=1,
            )
    assert result is None
