"""Cloudflare Python Workers entrypoint for garcar-payments."""
from workers import WorkerEntrypoint, Response
import json
import time
import stripe

_app = None
_asgi = None
try:
    import asgi
    from app.main import app as _fastapi_app
    _app = _fastapi_app
    _asgi = asgi
except Exception as exc:
    print(f"[entry] FastAPI app not loaded: {type(exc).__name__}")


def _json(data: dict, status: int = 200) -> Response:
    return Response(json.dumps(data, separators=(",", ":")), status=status, headers={"content-type": "application/json", "cache-control": "no-store"})


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        from urllib.parse import urlparse
        path = urlparse(str(getattr(request, "url", "") or "")).path or "/"

        if path in ("/health", "/livez", "/readyz", "/"):
            return _json({"status": "ok", "service": "garcar-payments", "edge": True, "fastapi": _app is not None})

        if path in ("/stripe-webhook", "/webhooks/stripe"):
            body = await request.text()
            sig = request.headers.get("Stripe-Signature") or request.headers.get("stripe-signature") or ""
            secret = getattr(self.env, "STRIPE_WEBHOOK_SECRET", "") or ""
            if not secret:
                return _json({"error": "webhook_not_configured"}, 503)
            try:
                event = stripe.Webhook.construct_event(body, sig, secret)
            except stripe.SignatureVerificationError:
                return _json({"error": "invalid_webhook_signature"}, 400)
            except Exception:
                return _json({"error": "invalid_webhook_payload"}, 400)
            if not event.get("id") or not event.get("type"):
                return _json({"error": "invalid_stripe_event"}, 400)
            try:
                await self.env.STRIPE_QUEUE.send({"payload": body, "signature": sig, "received_at": time.time(), "source": "stripe"})
                return _json({"status": "queued", "event_id": event["id"], "event_type": event["type"]})
            except Exception as exc:
                print(f"[webhook] queue send failed: {type(exc).__name__}")
                return _json({"error": "queue_failed"}, 503)

        if _app is not None and _asgi is not None:
            return await _asgi.fetch(_app, request, self.env)
        return _json({"error": "not_found", "path": path}, 404)

    async def queue(self, batch):
        from app.edge_queue import process_queued_stripe_event
        for message in batch.messages:
            process_queued_stripe_event(message.body)
