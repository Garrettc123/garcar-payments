from workers import WorkerEntrypoint, Response
import hashlib
import hmac
import json
import time

_app = None
_asgi = None
_load_attempted = False
_load_error: str | None = None
_SIGNATURE_TOLERANCE_SECONDS = 300


def _lazy_load_fastapi():
    global _app, _asgi, _load_attempted, _load_error
    if _load_attempted:
        return _app is not None
    _load_attempted = True
    try:
        import asgi
        from app.main import app as fastapi_app
        _app, _asgi = fastapi_app, asgi
        return True
    except Exception as e:
        _load_error = f"{type(e).__name__}: {e}"
        print(f"[entry] FastAPI lazy-load failed: {_load_error}")
        return False


def _json(data: dict, status: int = 200) -> Response:
    return Response(
        json.dumps(data, separators=(",", ":")),
        status=status,
        headers={"content-type": "application/json", "cache-control": "no-store", "x-garcar-edge": "1"},
    )


def _path_of(request) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(str(getattr(request, "url", "") or "")).path or "/"
    except Exception:
        return "/"


def _verify_stripe_signature(payload: str, signature: str, secret: str) -> bool:
    if not payload or not signature or not secret:
        return False
    timestamp = None
    signatures: list[str] = []
    for item in signature.split(","):
        key, _, value = item.strip().partition("=")
        if key == "t" and value:
            try:
                timestamp = int(value)
            except ValueError:
                return False
        elif key == "v1" and value:
            signatures.append(value)
    if timestamp is None or not signatures:
        return False
    if abs(int(time.time()) - timestamp) > _SIGNATURE_TOLERANCE_SECONDS:
        return False
    signed = f"{timestamp}.{payload}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = _path_of(request)
        t0 = time.time()

        if path in ("/", "/health", "/livez", "/readyz"):
            payload = {"status": "ok", "service": "garcar-payments", "edge": True, "fastapi_loaded": _app is not None,
                       "ms": round((time.time() - t0) * 1000, 2)}
            if path == "/readyz" and hasattr(self.env, "DB"):
                try:
                    from app.d1 import D1Repo
                    payload["d1"] = await D1Repo(self.env.DB).stats()
                except Exception as e:
                    payload["d1_error"] = type(e).__name__
            return _json(payload)

        if path in ("/stripe-webhook", "/webhooks/stripe"):
            body = await request.text()
            signature = request.headers.get("Stripe-Signature") or request.headers.get("stripe-signature") or ""
            secret = getattr(self.env, "STRIPE_WEBHOOK_SECRET", "") or ""
            if not secret:
                return _json({"error": "webhook_not_configured"}, status=503)
            if not _verify_stripe_signature(body, signature, secret):
                return _json({"error": "invalid_webhook_signature"}, status=400)
            try:
                event = json.loads(body)
                if not event.get("id") or not event.get("type"):
                    return _json({"error": "invalid_stripe_event"}, status=400)
                await self.env.STRIPE_QUEUE.send({"payload": body, "signature": signature, "received_at": time.time(), "source": "stripe", "path": path})
                return _json({"status": "queued", "event_id": event["id"], "event_type": event["type"],
                               "ms": round((time.time() - t0) * 1000, 2)})
            except Exception as e:
                print(f"[webhook] queue failed: {type(e).__name__}")
                return _json({"error": "queue_unavailable"}, status=503)

        if _lazy_load_fastapi() and _app is not None and _asgi is not None:
            try:
                return await _asgi.fetch(_app, request, self.env)
            except Exception as e:
                print(f"[asgi] {type(e).__name__}")
                return _json({"error": "asgi_failure"}, status=500)
        return _json({"error": "not_found", "path": path, "load_error": _load_error}, status=404)

    async def queue(self, batch):
        if not hasattr(self.env, "DB"):
            print("[queue] D1 binding missing; refusing to acknowledge payment event")
            raise RuntimeError("D1 binding is required for payment processing")
        from app.d1 import D1Repo
        repo = D1Repo(self.env.DB)
        await repo.ensure_schema()

        for message in batch.messages:
            body = message.body if hasattr(message, "body") else message
            if not isinstance(body, dict):
                raise RuntimeError("invalid queue message")
            raw = body.get("payload") or ""
            try:
                event = json.loads(raw) if isinstance(raw, str) else raw
            except Exception as e:
                raise RuntimeError("invalid Stripe JSON payload") from e
            event_id = event.get("id")
            event_type = event.get("type")
            obj = (event.get("data") or {}).get("object") or {}
            if not event_id or not event_type:
                raise RuntimeError("Stripe event missing id/type")

            is_new = await repo.record_billing_event(
                event_id=event_id, event_type=event_type, customer_id=obj.get("customer"),
                subscription_id=obj.get("subscription"), invoice_id=obj.get("invoice") or obj.get("id"),
                payload=raw if isinstance(raw, str) else json.dumps(raw),
            )
            if not is_new:
                print(f"[queue] duplicate event {event_id}")
                continue

            if event_type == "checkout.session.completed":
                payment_status = obj.get("payment_status")
                session_status = obj.get("status")
                if payment_status != "paid" and session_status != "complete":
                    print(f"[queue] checkout not paid: {event_id} status={payment_status}/{session_status}")
                    continue
                meta = obj.get("metadata") or {}
                plan = meta.get("garcar_plan") or ""
                email = ((obj.get("customer_details") or {}).get("email") or obj.get("customer_email") or "").lower().strip()
                if not plan or not email:
                    raise RuntimeError(f"paid checkout missing plan/email: {event_id}")
                await repo.enqueue_fulfillment(event_id, obj.get("id"), plan, email)
                await repo.grant_entitlement(event_id, email, plan)
                print(f"[queue] fulfillment + entitlement for {event_id} plan={plan}")
