"""Cloudflare Python Workers entrypoint for garcar-payments."""
from workers import WorkerEntrypoint, Response
import json
import time

_app = None
_asgi = None
try:
    import asgi
    from app.main import app as _fastapi_app
    _app = _fastapi_app
    _asgi = asgi
except Exception as exc:
    print(f"[entry] FastAPI app not loaded: {type(exc).__name__}")


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = getattr(request, "url", "") or ""
        from urllib.parse import urlparse
        path = urlparse(str(url)).path or "/"

        if path in ("/health", "/livez", "/readyz", "/"):
            return Response(json.dumps({"status": "ok", "service": "garcar-payments", "edge": True, "fastapi": _app is not None, "time": time.time()}), status=200, headers={"content-type": "application/json"})

        # Stripe always enters the durable queue first. This keeps the webhook
        # response fast and prevents external API calls from running in the
        # request path. Signature verification happens in the queue consumer.
        if path in ("/stripe-webhook", "/webhooks/stripe"):
            body = await request.text()
            sig = request.headers.get("Stripe-Signature") or request.headers.get("stripe-signature") or ""
            try:
                await self.env.STRIPE_QUEUE.send({"payload": body, "signature": sig, "received_at": time.time(), "source": "stripe"})
                return Response(json.dumps({"status": "queued"}), status=200, headers={"content-type": "application/json"})
            except Exception as exc:
                print(f"[webhook] queue send failed: {type(exc).__name__}")
                return Response(json.dumps({"error": "queue_failed"}), status=500, headers={"content-type": "application/json"})

        if _app is not None and _asgi is not None:
            return await _asgi.fetch(_app, request, self.env)
        return Response(json.dumps({"error": "not_found", "path": path}), status=404, headers={"content-type": "application/json"})

    async def queue(self, batch):
        from app.edge_queue import process_queued_stripe_event
        for message in batch.messages:
            process_queued_stripe_event(message.body)
