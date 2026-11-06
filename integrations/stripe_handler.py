"""Stripe webhook handler: payment-gated activation."""
import logging
import stripe
from integrations.config import Config
from integrations.hubspot_handler import close_deal
from integrations.supabase_handler import provision_tenant
from integrations.linear_handler import create_onboarding_project
from integrations.notion_handler import create_client_workspace
from integrations.docusign_handler import send_contract
from integrations.shopify_handler import fulfill_order

logger = logging.getLogger(__name__)
stripe.api_key = Config.STRIPE_SECRET_KEY
CHECKOUT_EVENTS = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}


def handle_stripe_webhook(payload: bytes, sig_header: str) -> dict:
    if not Config.STRIPE_WEBHOOK_SECRET or not Config.STRIPE_WEBHOOK_SECRET.strip():
        raise RuntimeError("Stripe webhook signing secret is not configured")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, Config.STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError as exc:
        raise ValueError("Invalid Stripe signature") from exc
    event_type = event["type"]
    data = event["data"]["object"]
    if event_type in CHECKOUT_EVENTS:
        if data.get("payment_status") != "paid":
            return {"status": "skipped", "event": event_type, "reason": "payment_not_confirmed"}
        if data.get("status") != "complete":
            return {"status": "skipped", "event": event_type, "reason": "checkout_not_complete"}
        _on_checkout_complete(data)
    elif event_type == "invoice.payment_succeeded":
        _on_subscription_renewed(data)
    elif event_type == "customer.subscription.deleted":
        _on_subscription_cancelled(data)
    elif event_type == "charge.refunded":
        _on_refund(data)
    else:
        return {"status": "ignored", "event": event_type}
    return {"status": "processed", "event": event_type}


def _on_checkout_complete(session: dict):
    details = session.get("customer_details") or {}
    if not isinstance(details, dict) or not details.get("email") or not session.get("id"):
        raise ValueError("Paid checkout requires session id and customer email")
    if session.get("payment_status") != "paid" or session.get("status") != "complete":
        raise ValueError("Checkout is not complete and paid")
    customer_email = details["email"]
    customer_name = details.get("name") or ""
    amount = session.get("amount_total", 0) / 100
    product_name = (session.get("metadata") or {}).get("product_name", "Unknown Product")
    tenant_id = provision_tenant(email=customer_email, name=customer_name,
        stripe_customer_id=session.get("customer"), product=product_name, amount=amount)
    close_deal(email=customer_email, name=customer_name, amount=amount, product=product_name)
    project_id = create_onboarding_project(client_name=customer_name,
        email=customer_email, product=product_name, tenant_id=tenant_id)
    create_client_workspace(name=customer_name, email=customer_email,
        product=product_name, linear_project_id=project_id, tenant_id=tenant_id)
    send_contract(email=customer_email, name=customer_name, product=product_name, amount=amount)
    shopify_order_id = (session.get("metadata") or {}).get("shopify_order_id")
    if shopify_order_id:
        fulfill_order(shopify_order_id)


def _on_subscription_renewed(invoice: dict):
    logger.info("Subscription renewal received")
    # TODO: durable lifecycle processing, scoped to the purchased subscription.


def _on_subscription_cancelled(subscription: dict):
    logger.info("Subscription cancellation received")
    # TODO: durable lifecycle processing, scoped to the purchased subscription.


def _on_refund(charge: dict):
    logger.warning("Refund received")
    # TODO: durable lifecycle processing, scoped to the refunded purchase.
