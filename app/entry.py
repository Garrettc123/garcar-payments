"""Cloudflare Python Workers entrypoint for garcar-payments."""
from workers import WorkerEntrypoint, Response
import json
import re
import time

from app.stripe_sig import SignatureError, parse_verified_event

_app = None
_asgi = None
try:
    import asgi
    from app.main import app as _fastapi_app
    _app = _fastapi_app
    _asgi = asgi
except Exception as exc:
    print(f"[entry] FastAPI app not loaded: {type(exc).__name__}")

TRACE_RE = re.compile(r"^gc_(test|stage|live)_([0-9]{8})_([0-9A-HJKMNP-TV-Z]{26})$")
ALLOWED = {
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
    "payment_intent.succeeded",
    "payment_intent.payment_failed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}


def _json(data: dict, status: int = 200) -> Response:
    return Response(
        json.dumps(data, separators=(",", ":")),
        status=status,
        headers={"content-type": "application/json", "cache-control": "no-store"},
    )


def _resolve_trace(event: dict):
    """Best-effort CMC trace extraction. Never blocks fulfillment.

    Payment Links and /create-checkout-session do not set metadata.trace_id.
    Aborting those events killed the revenue loop. Signature + ALLOWED still gate.
    """
    obj = ((event.get("data") or {}).get("object") or {})
    meta = obj.get("metadata") or {}
    raw = meta.get("trace_id") or meta.get("garcar.trace_id") or meta.get("garcar_trace_id")
    if raw and TRACE_RE.match(str(raw)):
        return {"trace_id": raw, "decision": "commit", "reason": "metadata.trace_id"}
    if raw:
        return {"trace_id": None, "decision": "commit", "reason": "malformed_metadata_trace_id_ignored"}
    return {"trace_id": None, "decision": "commit", "reason": "no_trace_id_plain_stripe"}


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        from urllib.parse import urlparse
        path = urlparse(str(getattr(request, "url", "") or "")).path or "/"

        if path in ("/health", "/healthz", "/livez", "/readyz", "/"):
            return _json({"status": "ok", "service": "garcar-payments", "edge": True, "fastapi": _app is not None})

        if path in ("/stripe-webhook", "/webhooks/stripe"):
            body = await request.text()
            sig = request.headers.get("Stripe-Signature") or request.headers.get("stripe-signature") or ""
            secret = getattr(self.env, "STRIPE_WEBHOOK_SECRET", "") or ""
            if not secret:
                return _json({"error": "webhook_not_configured"}, 503)
            if not sig:
                return _json({"error": "invalid_webhook_signature", "reason": "missing_header"}, 400)
            try:
                event = parse_verified_event(body, sig, secret)
            except SignatureError:
                return _json({"error": "invalid_webhook_signature"}, 400)
            except ValueError:
                return _json({"error": "invalid_webhook_payload"}, 400)
            if not event.get("id") or not event.get("type"):
                return _json({"error": "invalid_stripe_event"}, 400)
            if event["type"] not in ALLOWED:
                return _json({"received": True, "ignored": True, "event_type": event["type"]})
            gate = _resolve_trace(event)
            # Always queue ALLOWED + signature-valid events. trace_id is optional.
            try:
                await self.env.STRIPE_QUEUE.send({
                    "payload": body,
                    "signature": sig,
                    "received_at": time.time(),
                    "source": "stripe",
                    "trace_id": gate["trace_id"],
                    "event_id": event["id"],
                    "event_type": event["type"],
                    "cmc_reason": gate["reason"],
                })
                return _json({
                    "received": True,
                    "queued": True,
                    "trace_id": gate["trace_id"],
                    "cmc_decision": gate["decision"],
                    "cmc_reason": gate["reason"],
                    "event_id": event["id"],
                    "event_type": event["type"],
                })
            except Exception as exc:
                print(f"[webhook] queue send failed: {type(exc).__name__}")
                return _json({"error": "queue_failed"}, 503)

        if _app is not None and _asgi is not None:
            return await _asgi.fetch(_app, request, self.env)
        return _json({"error": "not_found", "path": path}, 404)

    async def queue(self, batch):
        from app.edge_queue import process_queued_stripe_event
        for message in batch.messages:
            await process_queued_stripe_event(message.body, self.env)
