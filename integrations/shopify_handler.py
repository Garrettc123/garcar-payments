"""Shopify Admin API — order fulfillment and product management."""
import httpx
import logging
from integrations.config import Config

logger = logging.getLogger(__name__)


def _client():
    return httpx.Client(
        base_url=f"https://{Config.SHOPIFY_STORE_DOMAIN}/admin/api/2024-04",
        headers={
            "X-Shopify-Access-Token": Config.SHOPIFY_ADMIN_TOKEN,
            "Content-Type": "application/json"
        }
    )


def fulfill_order(order_id: str) -> dict:
    """Mark a Shopify order as fulfilled (digital delivery)."""
    with _client() as c:
        # Get fulfillment orders
        r = c.get(f"/orders/{order_id}/fulfillment_orders.json")
        r.raise_for_status()
        fo = r.json()["fulfillment_orders"]
        if not fo:
            logger.warning(f"No fulfillment orders for Shopify order {order_id}")
            return {}
        fo_id = fo[0]["id"]
        # Create fulfillment
        payload = {
            "fulfillment": {
                "line_items_by_fulfillment_order": [{"fulfillment_order_id": fo_id}],
                "notify_customer": True,
                "tracking_info": {
                    "company": "Garcar Enterprise Digital Delivery",
                    "number": f"GARCAR-{order_id}",
                    "url": "https://garcar.io/access"
                }
            }
        }
        r2 = c.post("/fulfillments.json", json=payload)
        r2.raise_for_status()
        result = r2.json()["fulfillment"]
        logger.info(f"Shopify order fulfilled: {order_id} → {result['id']}")
        return result


def create_product(title: str, price: str, sku: str,
                    description: str = "", product_type: str = "Digital") -> dict:
    """Create a Shopify product programmatically."""
    with _client() as c:
        payload = {
            "product": {
                "title": title,
                "body_html": description,
                "product_type": product_type,
                "status": "active",
                "variants": [{"price": price, "sku": sku, "requires_shipping": False}]
            }
        }
        r = c.post("/products.json", json=payload)
        r.raise_for_status()
        product = r.json()["product"]
        logger.info(f"Shopify product created: {product['id']} — {title}")
        return product


def handle_shopify_webhook(payload: dict, topic: str):
    """Route inbound Shopify webhook to appropriate handler."""
    if topic == "orders/create":
        order_id = str(payload.get("id"))
        logger.info(f"Shopify order created: {order_id}")
        # Orders paid via Shopify checkout trigger Stripe separately
        # This handler catches manual/POS orders
    elif topic == "orders/paid":
        order_id = str(payload.get("id"))
        fulfill_order(order_id)
    elif topic == "products/update":
        product_id = payload.get("id")
        logger.info(f"Shopify product updated: {product_id}")
