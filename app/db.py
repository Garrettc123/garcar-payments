import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Float
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


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    stripe_subscription_id = Column(String(255), unique=True, index=True, nullable=False)
    stripe_customer_id = Column(String(255), index=True, nullable=True)
    customer_email = Column(String(255), nullable=True)
    status = Column(String(64), index=True, nullable=False, default="active")
    plan = Column(String(64), nullable=True)
    mrr = Column(Float, default=0.0)
    current_period_end = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)
