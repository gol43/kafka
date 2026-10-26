import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import Boolean, DateTime, LargeBinary, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CleanerJob(Base):
    __tablename__ = "cleaner_jobs"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "cleaner"}
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="waiting", index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
