"""
Cloudflare Python Workers entrypoint for garcar-payments.

Serves HTTP via FastAPI ASGI when available, otherwise a minimal health handler.
Consumes stripe-events Queue for durable Stripe processing.
"""

from workers import WorkerEntrypoint, Response
import json
import time

# Try full FastAPI app; fall back to minimal handler if heavy deps missing on Workers
_app = None
_asgi = None
try:
    import asgi
    from app.main import app as _fastapi_app
    _app = _fastapi_app
    _asgi = asgi
except Exception as e:
    print(f"[entry] FastAPI app not loaded ({e}); using minimal handler")


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = getattr(request, "url", "") or ""
        path = ""
        try:
            from urllib.parse import urlparse
            path = urlparse(str(url)).path or "/"
        except Exception:
            path = "/"

        # Health endpoints always available
        if path in ("/health", "/livez", "/readyz", "/"):
            return Response(
                json.dumps({
                    "status": "ok",
                    "service": "garcar-payments",
                    "edge": True,
                    "fastapi": _app is not None,
                    "time": time.time(),
                }),
                status=200,
                headers={"content-type": "application/json"},
            )

        # Stripe webhook: verify is optional here; enqueue for durable processing
        if path in ("/stripe-webhook", "/webhooks/stripe") and _app is None:
            try:
                body = await request.text()
            except Exception:
                body = ""
            sig = ""
            try:
                sig = request.headers.get("Stripe-Signature") or request.headers.get("stripe-signature") or ""
            except Exception:
                pass
            try:
                await self.env.STRIPE_QUEUE.send({
                    "payload": body,
                    "signature": sig,
                    "received_at": time.time(),
                    "source": "stripe",
                })
                return Response(
                    json.dumps({"status": "queued"}),
                    status=200,
                    headers={"content-type": "application/json"},
                )
            except Exception as e:
                print(f"[webhook] queue send failed: {e}")
                return Response(
                    json.dumps({"error": "queue_failed", "detail": str(e)}),
                    status=500,
                    headers={"content-type": "application/json"},
                )

        if _app is not None and _asgi is not None:
            return await _asgi.fetch(_app, request, self.env)

        return Response(
            json.dumps({"error": "not_found", "path": path}),
            status=404,
            headers={"content-type": "application/json"},
        )

    async def queue(self, batch):
        for message in batch.messages:
            try:
                body = message.body
                payload = body.get("payload") if isinstance(body, dict) else body
                print(f"[queue] stripe event received at {body.get('received_at') if isinstance(body, dict) else 'n/a'}")
                # Wire backend.payments processing when packages are available on Workers
            except Exception as e:
                print(f"[queue] failed: {e}")
                raise
