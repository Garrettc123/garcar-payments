"""Garcar Payments — FastAPI entry point.
Routes Stripe and Shopify webhooks through the cross-system integration layer.
Garcar Base Contract: /health /meta /metrics /events.
"""
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
import logging

from integrations.stripe_handler import handle_stripe_webhook
from integrations.shopify_handler import handle_shopify_webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

SYSTEM = "garcar-payments"
ROLE = "payments"
VERSION = "2.0.0"
CONTRACT_VERSION = "1.0.0"

app = FastAPI(
    title="Garcar Payments API",
    description="Cross-system integration: Stripe → HubSpot → Supabase → Linear → Notion → DocuSign → Hunter → Shopify → HuggingFace",
    version=VERSION,
)

_events: deque[dict[str, Any]] = deque(maxlen=1000)
_counters: dict[str, int] = {
    "requests_total": 0,
    "stripe_webhooks": 0,
    "shopify_webhooks": 0,
    "health_checks": 0,
    "meta_checks": 0,
    "metrics_checks": 0,
    "events_checks": 0,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_event(topic: str, source: str, payload: dict[str, Any] | None = None) -> None:
    _events.append({
        "topic": topic,
        "source": source,
        "payload": payload or {},
        "timestamp": _now(),
    })


@app.get("/health")
async def health():
    _counters["health_checks"] += 1
    _counters["requests_total"] += 1
    return {
        "status": "ok",
        "system": SYSTEM,
        "version": VERSION,
        "timestamp": _now(),
        "service": SYSTEM,
    }


@app.get("/meta")
async def meta():
    _counters["meta_checks"] += 1
    _counters["requests_total"] += 1
    return {
        "system": SYSTEM,
        "role": ROLE,
        "contract_version": CONTRACT_VERSION,
        "endpoints": ["/health", "/meta", "/metrics", "/events"],
        "event_bus_topic_schema": "garcar.{system}.{event_type}",
    }


@app.get("/metrics")
async def metrics():
    _counters["metrics_checks"] += 1
    _counters["requests_total"] += 1
    return dict(_counters)


@app.get("/events")
async def events():
    _counters["events_checks"] += 1
    _counters["requests_total"] += 1
    ev = list(_events)
    return {"events": ev, "total": len(ev)}


@app.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature")
):
    payload = await request.body()
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
    try:
        result = handle_stripe_webhook(payload, stripe_signature)
        _counters["stripe_webhooks"] += 1
        _counters["requests_total"] += 1
        _record_event("garcar.garcar-payments.stripe_webhook", "stripe", {"ok": True})
        return JSONResponse(content=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error")


@app.post("/webhooks/shopify")
async def shopify_webhook(
    request: Request,
    x_shopify_topic: str = Header(None, alias="X-Shopify-Topic")
):
    payload = await request.json()
    topic = x_shopify_topic or "unknown"
    try:
        handle_shopify_webhook(payload, topic)
        _counters["shopify_webhooks"] += 1
        _counters["requests_total"] += 1
        _record_event("garcar.garcar-payments.shopify_webhook", "shopify", {"topic": topic})
        return JSONResponse(content={"status": "processed", "topic": topic})
    except Exception as e:
        logger.error(f"Shopify webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error")


@app.get("/integrations/status")
async def integration_status():
    """Quick check of which env vars are configured."""
    import os
    keys = [
        "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
        "HUBSPOT_TOKEN", "SUPABASE_URL", "SUPABASE_SERVICE_KEY",
        "LINEAR_API_KEY", "LINEAR_TEAM_ID",
        "NOTION_TOKEN", "NOTION_CLIENTS_DB_ID",
        "DOCUSIGN_ACCOUNT_ID", "DOCUSIGN_ACCESS_TOKEN",
        "HUNTER_API_KEY", "SHOPIFY_STORE_DOMAIN", "SHOPIFY_ADMIN_TOKEN",
        "HF_TOKEN", "GITHUB_TOKEN"
    ]
    return {
        k: ("✅ set" if os.environ.get(k) else "❌ missing")
        for k in keys
    }
