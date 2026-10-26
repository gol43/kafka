from datetime import datetime
from typing import ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DialogChunk(Base):
    __tablename__ = "dialog_chunks"
    __table_args__ = (
        UniqueConstraint("call_id", "part", name="uq_dialog_chunks_call_part"),
        {"schema": "kafka"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    part: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_last: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DialogState(Base):
    __tablename__ = "dialog_state"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "kafka"}

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="collecting"
    )
    last_part: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
