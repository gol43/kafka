import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "copilot_ai_q_score"


class Base(DeclarativeBase):
    """Базовый класс моделей схемы Analyzer."""


class Dialog(Base):
    """Входящий диалог, который ещё не завершил полный анализ."""

    __tablename__ = "dialogs"
    __table_args__ = (
        Index("ix_dialogs_expires_at", "expires_at"),
        Index(
            "ix_dialogs_unfinished_work_date",
            "work_date",
            "call_id",
            postgresql_where=text("status IN ('waiting', 'processing')"),
        ),
        {"schema": SCHEMA},
    )

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False)
    client_epk: Mapped[str] = mapped_column(String(128), nullable=False)
    client_fio: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    required_analyzers: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    error_code: Mapped[str | None] = mapped_column(String(128))
    criteria_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
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
    """Персистентное задание worker-a для одного входящего диалога."""

    __tablename__ = "analysis_tasks"
    __table_args__ = (
        UniqueConstraint("call_id", name="uq_analysis_task_call"),
        Index(
            "ix_analysis_tasks_waiting_created",
            "created_at",
            postgresql_where=text("status = 'waiting'"),
        ),
        Index(
            "ix_analysis_tasks_processing_claimed",
            "claimed_at",
            postgresql_where=text("status = 'processing'"),
        ),
        Index("ix_analysis_tasks_expires_at", "expires_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.dialogs.call_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
        Index(
            "ix_dialog_reports_manager_occurred",
            "manager_id",
            "occurred_at",
        ),
        Index("ix_dialog_reports_expires_at", "expires_at"),
        {"schema": SCHEMA},
    )

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False)
    client_epk: Mapped[str] = mapped_column(String(128), nullable=False)
    client_fio: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    hygiene_results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    deposit_results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risk_results: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    audio_results: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    factor_results: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    hygiene_score: Mapped[int] = mapped_column(Integer, nullable=False)
    deposit_score: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
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
        Index("ix_dashboard_aggregates_expires_at", "expires_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False)
    aggregate_date: Mapped[date] = mapped_column(Date, nullable=False)
    manager_role: Mapped[str] = mapped_column(String(32), nullable=False)
    dialogs_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dialog_score_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dialog_score_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    daily_risks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    weekly_metrics: Mapped[dict | None] = mapped_column(JSONB)
    quarter_score_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    month_score_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DashboardSnapshot(Base):
    """Готовые ответы dashboard для одного менеджера и одной даты."""

    __tablename__ = "dashboard_snapshots"
    __table_args__ = (
        UniqueConstraint("manager_id", "report_date", name="uq_dashboard_snapshot"),
        Index("ix_dashboard_snapshots_expires_at", "expires_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    manager_role: Mapped[str] = mapped_column(String(32), nullable=False)
    source_date: Mapped[date] = mapped_column(Date, nullable=False)
    carried_forward: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    q_score: Mapped[dict] = mapped_column(JSONB, nullable=False)
    risks: Mapped[list] = mapped_column(JSONB, nullable=False)
    certain_client_risks: Mapped[dict] = mapped_column(JSONB, nullable=False)
    strengths: Mapped[list] = mapped_column(JSONB, nullable=False)
    improvements: Mapped[list] = mapped_column(JSONB, nullable=False)
    certain_improvement_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
