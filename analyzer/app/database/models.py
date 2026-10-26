import uuid
from datetime import date, datetime
from typing import ClassVar

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
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
    """Очищенный диалог вместе с итогом всех обязательных анализаторов."""

    __tablename__ = "dialogs"
    __table_args__: ClassVar[dict[str, str]] = {"schema": SCHEMA}

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    manager_name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_epk: Mapped[str] = mapped_column(String(128), nullable=False)
    client_fio: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str | None] = mapped_column(String(64))
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)
    dialog_data: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    required_analyzers: Mapped[list] = mapped_column(JSONB, nullable=False)
    analysis_results: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    analysis_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="waiting", index=True
    )
    criteria_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    q_score: Mapped[float | None] = mapped_column(Float)
    general_score: Mapped[float | None] = mapped_column(Float)
    deposit_topic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deposit_score: Mapped[float | None] = mapped_column(Float)
    deviations_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dialog_report: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    critical_violation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    daily_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.daily_reports.id", ondelete="SET NULL"), index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisTask(Base):
    """Сохраняемое задание внутренней очереди Analyzer.

    Таблица нужна для восстановления незавершённой работы после перезапуска pod.
    Она не является отчётом и не возвращается через публичный API.
    """

    __tablename__ = "analysis_tasks"
    __table_args__ = (
        UniqueConstraint(
            "task_type", "entity_key", "report_version", name="uq_task_entity_version"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_key: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="waiting", index=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DailyReport(Base):
    """Один дневной отчёт одного менеджера."""

    __tablename__ = "daily_reports"
    __table_args__ = (
        UniqueConstraint(
            "manager_id", "report_date", "report_version", name="uq_daily_report"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    report_version: Mapped[str] = mapped_column(String(64), nullable=False)
    q_score: Mapped[float | None] = mapped_column(Float)
    score_sum: Mapped[float | None] = mapped_column(Float)
    communications_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    summary: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_call_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    weekly_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.weekly_reports.id", ondelete="SET NULL"), index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WeeklyReport(Base):
    """Один недельный отчёт одного менеджера."""

    __tablename__ = "weekly_reports"
    __table_args__ = (
        UniqueConstraint(
            "manager_id",
            "period_start",
            "period_end",
            "report_version",
            name="uq_weekly_report",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    report_version: Mapped[str] = mapped_column(String(64), nullable=False)
    q_score: Mapped[float | None] = mapped_column(Float)
    score_sum: Mapped[float | None] = mapped_column(Float)
    communications_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    summary: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_daily_report_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    four_week_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.four_week_reports.id", ondelete="SET NULL"), index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FourWeekReport(Base):
    """Отчёт менеджера, построенный строго из четырёх недельных отчётов."""

    __tablename__ = "four_week_reports"
    __table_args__ = (
        UniqueConstraint(
            "manager_id",
            "period_start",
            "period_end",
            "report_version",
            name="uq_four_week_report",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    report_version: Mapped[str] = mapped_column(String(64), nullable=False)
    q_score: Mapped[float | None] = mapped_column(Float)
    score_sum: Mapped[float | None] = mapped_column(Float)
    communications_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    summary: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_weekly_report_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    quarterly_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.quarterly_reports.id", ondelete="SET NULL"), index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuarterlyReport(Base):
    """Квартальный отчёт менеджера из трёх four-week отчётов."""

    __tablename__ = "quarterly_reports"
    __table_args__ = (
        UniqueConstraint(
            "manager_id",
            "period_start",
            "period_end",
            "report_version",
            name="uq_quarterly_report",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting")
    report_version: Mapped[str] = mapped_column(String(64), nullable=False)
    q_score: Mapped[float | None] = mapped_column(Float)
    score_sum: Mapped[float | None] = mapped_column(Float)
    communications_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    summary: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_four_week_report_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DialogMetricResult(Base):
    """Нормализованный результат одного критерия одного звонка."""

    __tablename__ = "dialog_metric_results"
    __table_args__ = (
        UniqueConstraint("call_id", "metric_code", name="uq_dialog_metric"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.dialogs.call_id", ondelete="CASCADE"), index=True
    )
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    client_epk: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    metric_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metric_title: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_block: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    penalty: Mapped[int] = mapped_column(Integer, nullable=False)
    quote: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    included_in_analytics: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class ManagerMetricDailyStat(Base):
    """Готовая дневная статистика одной метрики менеджера."""

    __tablename__ = "manager_metric_daily_stats"
    __table_args__ = (
        UniqueConstraint(
            "manager_id", "metric_code", "stat_date", name="uq_manager_metric_day"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    metric_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stat_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    communications_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_percent: Mapped[float] = mapped_column(Float, nullable=False)


class ManagerDashboardSnapshot(Base):
    """Полностью готовый ответ основной страницы менеджера."""

    __tablename__ = "manager_dashboard_snapshots"
    __table_args__ = (
        UniqueConstraint("manager_id", "snapshot_date", name="uq_manager_dashboard"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ClientMetricSnapshot(Base):
    """Готовая детализация клиента и выбранного нарушения."""

    __tablename__ = "client_metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "manager_id",
            "client_epk",
            "metric_code",
            "snapshot_date",
            name="uq_client_metric_snapshot",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    client_epk: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    metric_code: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ManagerMetricSnapshot(Base):
    """Готовая детализация метрики для popup зоны развития."""

    __tablename__ = "manager_metric_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "manager_id", "metric_code", "snapshot_date", name="uq_manager_metric_snapshot"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manager_id: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    metric_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
