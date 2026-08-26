"""Garcar Payments — FastAPI entry point.
Routes Stripe and Shopify webhooks through the cross-system integration layer.
"""
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

app = FastAPI(
    title="Garcar Payments API",
    description="Cross-system integration: Stripe → HubSpot → Supabase → Linear → Notion → DocuSign → Hunter → Shopify → HuggingFace",
    version="2.0.0"
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "garcar-payments", "version": "2.0.0"}


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
