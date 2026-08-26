import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, UniqueConstraint
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


JOB_STATUS_PENDING = "pending"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_DONE = "done"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_DEAD = "dead"


class FulfillmentJob(Base):
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    email_sent = Column(Boolean, nullable=False, default=False)


class DownloadEntitlement(Base):
    __tablename__ = "download_entitlements"
    __table_args__ = (UniqueConstraint("stripe_event_id", "customer_email", "plan", name="uq_entitlement_event_email_plan"),)
    id = Column(Integer, primary_key=True, index=True)
    stripe_event_id = Column(String(255), index=True, nullable=False)
    customer_email = Column(String(320), index=True, nullable=False)
    plan = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)
