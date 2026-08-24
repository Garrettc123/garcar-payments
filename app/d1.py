"""
Edge-native D1 repository for garcar-payments.

Zero SQLAlchemy. Pure D1 prepared statements.
Used exclusively on Cloudflare Workers.
Idempotent, fail-closed on write errors, observable.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional


# ── Schema (run once via wrangler d1 execute or migration) ────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS billing_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    customer_id TEXT,
    subscription_id TEXT,
    invoice_id TEXT,
    payload TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS fulfillment_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stripe_event_id TEXT NOT NULL UNIQUE,
    checkout_session_id TEXT,
    plan TEXT,
    customer_email TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    email_sent INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL
);

CREATE TABLE IF NOT EXISTS download_entitlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stripe_event_id TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    plan TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_billing_event_id ON billing_events(event_id);
CREATE INDEX IF NOT EXISTS idx_fulfillment_status ON fulfillment_jobs(status);
CREATE INDEX IF NOT EXISTS idx_entitlement_email_plan ON download_entitlements(customer_email, plan);
"""


class D1Repo:
    """Thin, hardened repository over env.DB."""

    def __init__(self, db):
        self.db = db

    async def ensure_schema(self) -> None:
        # D1 supports multiple statements in one execute in recent runtimes
        for stmt in SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await self.db.prepare(stmt).run()

    # ── Billing Events (idempotent) ───────────────────────────────────────────

    async def record_billing_event(
        self,
        event_id: str,
        event_type: str,
        customer_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        invoice_id: Optional[str] = None,
        payload: Optional[str] = None,
    ) -> bool:
        """Insert event. Returns True if new, False if duplicate."""
        now = time.time()
        try:
            await self.db.prepare(
                """
                INSERT INTO billing_events
                    (event_id, event_type, customer_id, subscription_id, invoice_id, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
            ).bind(
                event_id, event_type, customer_id, subscription_id, invoice_id, payload, now
            ).run()
            return True
        except Exception as e:
            # Unique violation → already processed
            if "UNIQUE" in str(e).upper() or "constraint" in str(e).lower():
                return False
            raise

    # ── Fulfillment Jobs ──────────────────────────────────────────────────────

    async def enqueue_fulfillment(
        self,
        stripe_event_id: str,
        checkout_session_id: Optional[str],
        plan: Optional[str],
        customer_email: Optional[str],
    ) -> bool:
        """Create pending job. Returns True if new."""
        now = time.time()
        try:
            await self.db.prepare(
                """
                INSERT INTO fulfillment_jobs
                    (stripe_event_id, checkout_session_id, plan, customer_email,
                     status, attempts, email_sent, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', 0, 0, ?, ?)
                """
            ).bind(
                stripe_event_id, checkout_session_id, plan, customer_email, now, now
            ).run()
            return True
        except Exception as e:
            if "UNIQUE" in str(e).upper() or "constraint" in str(e).lower():
                return False
            raise

    async def claim_pending_jobs(self, limit: int = 10) -> list[dict]:
        """Atomic-ish claim of pending jobs (best-effort on D1)."""
        rows = await self.db.prepare(
            """
            SELECT id, stripe_event_id, checkout_session_id, plan, customer_email, attempts
            FROM fulfillment_jobs
            WHERE status = 'pending' AND attempts < 5
            ORDER BY created_at ASC
            LIMIT ?
            """
        ).bind(limit).all()
        results = []
        for r in (rows.results if hasattr(rows, "results") else rows):
            job = dict(r)
            await self.db.prepare(
                "UPDATE fulfillment_jobs SET status = 'processing', attempts = attempts + 1, updated_at = ? WHERE id = ?"
            ).bind(time.time(), job["id"]).run()
            results.append(job)
        return results

    async def complete_job(self, job_id: int, email_sent: bool = False) -> None:
        await self.db.prepare(
            """
            UPDATE fulfillment_jobs
            SET status = 'done', email_sent = ?, completed_at = ?, updated_at = ?
            WHERE id = ?
            """
        ).bind(1 if email_sent else 0, time.time(), time.time(), job_id).run()

    async def fail_job(self, job_id: int, error: str) -> None:
        await self.db.prepare(
            """
            UPDATE fulfillment_jobs
            SET status = CASE WHEN attempts >= 5 THEN 'dead' ELSE 'pending' END,
                last_error = ?, updated_at = ?
            WHERE id = ?
            """
        ).bind(error[:2000], time.time(), job_id).run()

    # ── Entitlements ──────────────────────────────────────────────────────────

    async def grant_entitlement(
        self, stripe_event_id: str, customer_email: str, plan: str
    ) -> None:
        await self.db.prepare(
            """
            INSERT INTO download_entitlements (stripe_event_id, customer_email, plan, created_at)
            VALUES (?, ?, ?, ?)
            """
        ).bind(stripe_event_id, customer_email.lower().strip(), plan, time.time()).run()

    async def has_entitlement(
        self, customer_email: str, plan: str, stripe_event_id: Optional[str] = None
    ) -> bool:
        if stripe_event_id:
            row = await self.db.prepare(
                """
                SELECT 1 FROM download_entitlements
                WHERE customer_email = ? AND plan = ? AND stripe_event_id = ?
                LIMIT 1
                """
            ).bind(customer_email.lower().strip(), plan, stripe_event_id).first()
        else:
            row = await self.db.prepare(
                """
                SELECT 1 FROM download_entitlements
                WHERE customer_email = ? AND plan = ?
                LIMIT 1
                """
            ).bind(customer_email.lower().strip(), plan).first()
        return row is not None

    # ── Health / metrics ──────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        try:
            events = await self.db.prepare("SELECT COUNT(*) as c FROM billing_events").first()
            jobs = await self.db.prepare(
                "SELECT status, COUNT(*) as c FROM fulfillment_jobs GROUP BY status"
            ).all()
            ents = await self.db.prepare("SELECT COUNT(*) as c FROM download_entitlements").first()
            return {
                "billing_events": (events["c"] if events else 0),
                "fulfillment_by_status": {
                    r["status"]: r["c"] for r in (jobs.results if hasattr(jobs, "results") else jobs or [])
                },
                "entitlements": (ents["c"] if ents else 0),
            }
        except Exception as e:
            return {"error": str(e)}
