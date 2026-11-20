import logging
import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("garcar.payments.db")


def resolve_database_url() -> str:
    """Resolve the SQLAlchemy URL.

    - DATABASE_URL set: use it (Postgres in production). Bare ``postgres://`` /
      ``postgresql://`` URLs are rewritten to the psycopg v3 driver.
    - Unset on a serverless runtime (Vercel / AWS Lambda): the deployment
      bundle is read-only, so a relative SQLite file cannot be opened and the
      app crashed at startup. Fall back to /tmp so the process can boot, and log
      loudly: /tmp is ephemeral, so billing events and fulfillment jobs are NOT
      durable until DATABASE_URL is configured.
    - Unset elsewhere (local dev, tests): ./local.db as before.
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url
    if os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        logger.error(
            "DATABASE_URL is not set on a serverless runtime; using ephemeral "
            "SQLite in /tmp. Data will be lost on cold start. Set DATABASE_URL to Postgres."
        )
        return "sqlite:////tmp/garcar_payments.db"
    return "sqlite:///./local.db"


DATABASE_URL = resolve_database_url()
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class BillingEvent(Base):
    __tablename__ = "billing_events"
    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(255), unique=True, index=True, nullable=False)
    event_type = Column(String(255), index=True, nullable=False)
    customer_id = Column(String(255), nullable=True)
    subscription_id = Column(String(255), nullable=True)
    invoice_id = Column(String(255), nullable=True)
    payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


JOB_STATUS_PENDING = "pending"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_DEAD = "dead"


class FulfillmentJob(Base):
    __tablename__ = "fulfillment_jobs"
    __table_args__ = (UniqueConstraint("checkout_session_id", name="uq_fulfillment_checkout_session"),)
    MAX_ATTEMPTS = 5
    id = Column(Integer, primary_key=True, index=True)
    stripe_event_id = Column(String(255), unique=True, index=True, nullable=False)
    checkout_session_id = Column(String(255), index=True, nullable=False)
    stripe_customer_id = Column(String(255), index=True, nullable=True)
    plan = Column(String(100), nullable=True)
    customer_email = Column(String(320), nullable=True)
    status = Column(String(32), index=True, nullable=False, default=JOB_STATUS_PENDING)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    failed_stage = Column(String(64), nullable=True)
    hubspot_contact_id = Column(String(255), nullable=True)
    supabase_entitlement_id = Column(String(255), nullable=True)
    asana_project_id = Column(String(255), nullable=True)
    asana_task_id = Column(String(255), nullable=True)
    notion_event_id = Column(String(255), nullable=True)
    linear_issue_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    email_sent = Column(Boolean, nullable=False, default=False)


class IntegrationAction(Base):
    __tablename__ = "integration_actions"
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, index=True, nullable=False)
    stage = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    external_id = Column(String(255), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("job_id", "stage", name="uq_integration_action_job_stage"),)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(String(255), unique=True, index=True, nullable=False)
    customer_id = Column(String(255), index=True, nullable=True)
    plan = Column(String(100), nullable=True)
    unit_amount = Column(Integer, nullable=True)
    currency = Column(String(10), nullable=True, default="usd")
    status = Column(String(32), nullable=False, default="active")
    current_period_end = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DownloadEntitlement(Base):
    __tablename__ = "download_entitlements"
    id = Column(Integer, primary_key=True, index=True)
    stripe_event_id = Column(String(255), index=True, nullable=False)
    customer_email = Column(String(320), index=True, nullable=False)
    plan = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)
