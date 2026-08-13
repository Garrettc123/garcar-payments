import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")
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


# Job status constants
JOB_STATUS_PENDING = "pending"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_DEAD = "dead"  # exhausted retries


class FulfillmentJob(Base):
    """
    Durable fulfillment job table.

    Each checkout.session.completed event creates exactly one row (idempotent
    on stripe_event_id).  The worker retries up to MAX_ATTEMPTS times with
    exponential back-off; exhausted jobs are moved to status='dead' for
    manual inspection.
    """

    __tablename__ = "fulfillment_jobs"

    MAX_ATTEMPTS = 5

    id = Column(Integer, primary_key=True, index=True)
    stripe_event_id = Column(String(255), unique=True, index=True, nullable=False)
    checkout_session_id = Column(String(255), index=True, nullable=True)
    plan = Column(String(100), nullable=True)
    customer_email = Column(String(320), nullable=True)
    status = Column(String(32), index=True, nullable=False, default=JOB_STATUS_PENDING)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    # Audit trail
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    # Set to True once email has been sent so re-runs don't re-send
    email_sent = Column(Boolean, nullable=False, default=False)


class DownloadEntitlement(Base):
    """
    Records that a customer is entitled to download a specific product.
    Used by the signed-download endpoint to verify access before issuing a link.
    """

    __tablename__ = "download_entitlements"

    id = Column(Integer, primary_key=True, index=True)
    stripe_event_id = Column(String(255), index=True, nullable=False)
    customer_email = Column(String(320), index=True, nullable=False)
    plan = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)
