"""Перестраивает Analyzer вокруг диалогов и готовых витрин."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "analyzer_0004"
down_revision = "analyzer_0003"
branch_labels = None
depends_on = None

SCHEMA = "analyzer"


def upgrade() -> None:
    # Проект ещё не хранит production-данные. Миграция намеренно удаляет
    # старую экспериментальную модель отчётов и создаёт конечные пять таблиц.
    for table in (
        "analysis_tasks",
        "dialog_metric_results",
        "manager_metric_daily_stats",
        "manager_metric_snapshots",
        "client_metric_snapshots",
        "manager_dashboard_snapshots",
        "daily_reports",
        "weekly_reports",
        "four_week_reports",
        "quarterly_reports",
        "dialogs",
    ):
        op.execute(sa.text(f'DROP TABLE IF EXISTS "{SCHEMA}"."{table}" CASCADE'))

    op.create_table(
        "dialogs",
        sa.Column("call_id", sa.String(64), primary_key=True),
        sa.Column("manager_id", sa.String(8), nullable=False),
        sa.Column("client_epk", sa.String(128), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("cleaned_text", sa.Text(), nullable=False),
        sa.Column("required_analyzers", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="waiting"),
        sa.Column("error_code", sa.String(128)),
        sa.Column("criteria_version", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_dialogs_status_work_date_created", "dialogs", ["status", "work_date", "created_at"], schema=SCHEMA)
    op.create_index("ix_dialogs_manager_work_date", "dialogs", ["manager_id", "work_date"], schema=SCHEMA)

    op.create_table(
        "analysis_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("call_id", sa.String(64), sa.ForeignKey(f"{SCHEMA}.dialogs.call_id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="waiting"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("call_id", name="uq_analysis_task_call"),
        schema=SCHEMA,
    )
    op.create_index("ix_analysis_tasks_status_created", "analysis_tasks", ["status", "created_at"], schema=SCHEMA)

    op.create_table(
        "dialog_reports",
        sa.Column("call_id", sa.String(64), primary_key=True),
        sa.Column("manager_id", sa.String(8), nullable=False),
        sa.Column("client_epk", sa.String(128), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleaned_text", sa.Text(), nullable=False),
        sa.Column("hygiene_results", postgresql.JSONB(), nullable=False),
        sa.Column("deposit_results", postgresql.JSONB(), nullable=False),
        sa.Column("risk_results", postgresql.JSONB(), nullable=False),
        sa.Column("audio_results", postgresql.JSONB(), nullable=False),
        sa.Column("factor_results", postgresql.JSONB(), nullable=False),
        sa.Column("general_score", sa.Float(), nullable=False),
        sa.Column("deposit_score", sa.Float()),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("deposit_topic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("critical_violation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deviations_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("risks_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report_payload", postgresql.JSONB(), nullable=False),
        sa.Column("criteria_version", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_dialog_reports_manager_work_occurred", "dialog_reports", ["manager_id", "work_date", "occurred_at"], schema=SCHEMA)
    op.create_index("ix_dialog_reports_manager_client_occurred", "dialog_reports", ["manager_id", "client_epk", "occurred_at"], schema=SCHEMA)
    op.create_index("ix_dialog_reports_completed_at", "dialog_reports", ["completed_at"], schema=SCHEMA)

    op.create_table(
        "dashboard_aggregates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("manager_id", sa.String(8), nullable=False),
        sa.Column("aggregate_date", sa.Date(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("manager_id", "aggregate_date", name="uq_dashboard_aggregate"),
        schema=SCHEMA,
    )
    op.create_index("ix_dashboard_aggregates_date", "dashboard_aggregates", ["aggregate_date"], schema=SCHEMA)

    op.create_table(
        "dashboard_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("manager_id", sa.String(8), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("q_score_block", postgresql.JSONB(), nullable=False),
        sa.Column("client_risks_block", postgresql.JSONB(), nullable=False),
        sa.Column("client_risk_details", postgresql.JSONB(), nullable=False),
        sa.Column("strengths_block", postgresql.JSONB(), nullable=False),
        sa.Column("improvements_block", postgresql.JSONB(), nullable=False),
        sa.Column("improvement_details", postgresql.JSONB(), nullable=False),
        sa.Column("communications_block", postgresql.JSONB(), nullable=False),
        sa.Column("source_call_ids", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("manager_id", "report_date", name="uq_dashboard_snapshot"),
        schema=SCHEMA,
    )
    op.create_index("ix_dashboard_snapshots_date", "dashboard_snapshots", ["report_date"], schema=SCHEMA)


def downgrade() -> None:
    for table in (
        "dashboard_snapshots",
        "dashboard_aggregates",
        "dialog_reports",
        "analysis_tasks",
        "dialogs",
    ):
        op.drop_table(table, schema=SCHEMA)
