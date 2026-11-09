import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String

from app.database.connection import Base, JSON_TYPE


def utc_now():
    return datetime.now(timezone.utc)


class AnonymizationTask(Base):
    __tablename__ = "cleaner_jobs"
    __table_args__ = (
        Index("ix_anonymization_status_next", "status", "next_attempt_at"),
        Index("ix_anonymization_expires", "expires_at"),
        {"schema": "copilot_data_cleaner"},
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    call_id = Column(String(64), nullable=False, unique=True)
    payload = Column(JSON_TYPE, nullable=False)
    status = Column(String(20), nullable=False, default="waiting")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String(1000), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class CallbackDelivery(Base):
    __tablename__ = "callback_deliveries"
    __table_args__ = (
        Index("ix_delivery_status_next", "status", "next_attempt_at"),
        Index("ix_delivery_expires", "expires_at"),
        {"schema": "copilot_data_cleaner"},
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    call_id = Column(String(64), nullable=False, index=True)
    subscriber_name = Column(String(100), nullable=False)
    subscriber_url = Column(String(1000), nullable=False)
    body = Column(JSON_TYPE, nullable=False)
    status = Column(String(20), nullable=False, default="waiting")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(String(1000), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
