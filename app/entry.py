"""
Thin Cloudflare Python Workers entrypoint for garcar-payments.

Adapts the existing FastAPI app (app.main:app) to the Workers ASGI runtime
and adds the Queue consumer for Stripe events.
"""

from workers import WorkerEntrypoint
import asgi

# Import your existing FastAPI application
from app.main import app


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        """HTTP requests → FastAPI via ASGI adapter."""
        return await asgi.fetch(app, request, self.env)

    async def queue(self, batch):
        """
        Cloudflare Queues consumer for stripe-events.
        Heavy processing lives here so the webhook stays fast.
        """
        for message in batch.messages:
            try:
                body = message.body
                # body is the dict sent by the webhook producer:
                # { "payload": "...", "signature": "...", "received_at": ..., "source": "stripe" }
                payload = body.get("payload") if isinstance(body, dict) else body

                # TODO: call your existing fulfillment / ledger logic here
                # e.g. from backend.payments import process_stripe_event
                # await process_stripe_event(payload)

                print(f"[queue] processed Stripe event at {body.get('received_at') if isinstance(body, dict) else 'n/a'}")
            except Exception as e:
                print(f"[queue] failed: {e}")
                raise  # triggers retry → eventually DLQ
