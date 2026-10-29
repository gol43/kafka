import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "analyzer"


class Base(DeclarativeBase):
    """Базовый класс моделей схемы Analyzer."""


class Dialog(Base):
    """Входящий диалог, который ещё не завершил полный анализ."""

    __tablename__ = "dialogs"
    __table_args__ = (
        Index("ix_dialogs_status_work_date_created", "status", "work_date", "created_at"),
        Index("ix_dialogs_manager_work_date", "manager_id", "work_date"),
        {"schema": SCHEMA},
    )

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False)
    client_epk: Mapped[str] = mapped_column(String(128), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)
    required_analyzers: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    error_code: Mapped[str | None] = mapped_column(String(128))
    criteria_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalysisTask(Base):
    """Персистентное задание worker-а для одного входящего диалога."""

    __tablename__ = "analysis_tasks"
    __table_args__ = (
        UniqueConstraint("call_id", name="uq_analysis_task_call"),
        Index("ix_analysis_tasks_status_created", "status", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.dialogs.call_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DialogReport(Base):
    """Готовый завершённый анализ одного диалога."""

    __tablename__ = "dialog_reports"
    __table_args__ = (
        Index(
            "ix_dialog_reports_manager_work_occurred",
            "manager_id",
            "work_date",
            "occurred_at",
        ),
        Index(
            "ix_dialog_reports_manager_client_occurred",
            "manager_id",
            "client_epk",
            "occurred_at",
        ),
        Index("ix_dialog_reports_completed_at", "completed_at"),
        {"schema": SCHEMA},
    )

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False)
    client_epk: Mapped[str] = mapped_column(String(128), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)

    hygiene_results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    deposit_results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risk_results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    audio_results: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    factor_results: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    general_score: Mapped[float] = mapped_column(Float, nullable=False)
    deposit_score: Mapped[float | None] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    deposit_topic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    critical_violation: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    deviations_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    criteria_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DashboardAggregate(Base):
    """Промежуточная математика одного менеджера за один рабочий день."""

    __tablename__ = "dashboard_aggregates"
    __table_args__ = (
        UniqueConstraint("manager_id", "aggregate_date", name="uq_dashboard_aggregate"),
        Index("ix_dashboard_aggregates_date", "aggregate_date"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False)
    aggregate_date: Mapped[date] = mapped_column(Date, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DashboardSnapshot(Base):
    """Готовые данные пяти блоков и трёх popup одного менеджера."""

    __tablename__ = "dashboard_snapshots"
    __table_args__ = (
        UniqueConstraint("manager_id", "report_date", name="uq_dashboard_snapshot"),
        Index("ix_dashboard_snapshots_date", "report_date"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    q_score_block: Mapped[dict] = mapped_column(JSONB, nullable=False)
    client_risks_block: Mapped[list] = mapped_column(JSONB, nullable=False)
    client_risk_details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    strengths_block: Mapped[list] = mapped_column(JSONB, nullable=False)
    improvements_block: Mapped[list] = mapped_column(JSONB, nullable=False)
    improvement_details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    communications_block: Mapped[list] = mapped_column(JSONB, nullable=False)
    source_call_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
