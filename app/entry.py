"""
Cloudflare Python Workers entrypoint for garcar-payments.

Performance goals:
- Sub-10 ms cold-start for health endpoints (no heavy imports)
- Lazy-load FastAPI / Stripe / SQLAlchemy only when a real business route is hit
- Always prefer durable queue for Stripe webhooks on the edge
- Fail open for health, fail closed for money paths
"""

from workers import WorkerEntrypoint, Response
import json
import time

# ── Ultra-light globals (never import FastAPI at module level) ───────────────
_app = None
_asgi = None
_load_attempted = False
_load_error: str | None = None


def _lazy_load_fastapi():
    """Import the full stack only on first non-health request."""
    global _app, _asgi, _load_attempted, _load_error
    if _load_attempted:
        return _app is not None
    _load_attempted = True
    try:
        import asgi
        from app.main import app as fastapi_app
        _app = fastapi_app
        _asgi = asgi
        return True
    except Exception as e:
        _load_error = f"{type(e).__name__}: {e}"
        print(f"[entry] FastAPI lazy-load failed: {_load_error}")
        return False


def _json(data: dict, status: int = 200) -> Response:
    return Response(
        json.dumps(data, separators=(",", ":")),
        status=status,
        headers={
            "content-type": "application/json",
            "cache-control": "no-store",
            "x-garcar-edge": "1",
        },
    )


def _path_of(request) -> str:
    try:
        url = str(getattr(request, "url", "") or "")
        from urllib.parse import urlparse
        return urlparse(url).path or "/"
    except Exception:
        return "/"


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = _path_of(request)
        t0 = time.time()

        # ── Health paths: pure Python, zero imports beyond stdlib ─────────────
        if path in ("/health", "/livez", "/readyz", "/"):
            return _json({
                "status": "ok",
                "service": "garcar-payments",
                "edge": True,
                "fastapi_loaded": _app is not None,
                "load_attempted": _load_attempted,
                "load_error": _load_error,
                "ms": round((time.time() - t0) * 1000, 2),
            })

        # ── Stripe webhook: always try queue first (durable, non-blocking) ───
        if path in ("/stripe-webhook", "/webhooks/stripe"):
            try:
                body = await request.text()
            except Exception:
                body = ""
            sig = ""
            try:
                h = request.headers
                sig = h.get("Stripe-Signature") or h.get("stripe-signature") or ""
            except Exception:
                pass

            # Prefer durable queue
            try:
                await self.env.STRIPE_QUEUE.send({
                    "payload": body,
                    "signature": sig,
                    "received_at": time.time(),
                    "source": "stripe",
                    "path": path,
                })
                return _json({"status": "queued", "ms": round((time.time() - t0) * 1000, 2)})
            except Exception as e:
                print(f"[webhook] queue send failed: {e}")
                # Fall through to full app if queue unavailable

        # ── Business routes: lazy-load full FastAPI stack ─────────────────────
        if _lazy_load_fastapi() and _app is not None and _asgi is not None:
            try:
                return await _asgi.fetch(_app, request, self.env)
            except Exception as e:
                print(f"[asgi] error: {e}")
                return _json({"error": "asgi_failure", "detail": str(e)}, status=500)

        return _json({
            "error": "not_found",
            "path": path,
            "fastapi_loaded": False,
            "load_error": _load_error,
        }, status=404)

    async def queue(self, batch):
        """Durable Stripe event consumer. Keep this path light."""
        for message in batch.messages:
            try:
                body = message.body if hasattr(message, "body") else message
                if isinstance(body, dict):
                    received = body.get("received_at")
                    print(f"[queue] stripe event @ {received}")
                    # Future: call backend.payments.process_event(body["payload"], body.get("signature"))
                else:
                    print("[queue] raw message received")
                # Acknowledge by not raising
            except Exception as e:
                print(f"[queue] failed: {e}")
                raise  # let CF retry / DLQ
