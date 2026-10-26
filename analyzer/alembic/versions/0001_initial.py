"""Начальная схема Analyzer с отдельной таблицей для каждого типа отчёта."""

import sqlalchemy as sa

from alembic import op

revision = "analyzer_0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "analyzer"


def _report_columns() -> list[sa.Column]:
    """Общие колонки агрегированных отчётов."""

    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("manager_id", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("report_version", sa.String(64), nullable=False),
        sa.Column("q_score", sa.Float()),
        sa.Column("score_sum", sa.Float()),
        sa.Column("communications_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    ]


def upgrade() -> None:
    """Создаёт очередь, диалоги и четыре уровня отчётов."""

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "quarterly_reports",
        *_report_columns(),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("source_four_week_report_ids", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "manager_id",
            "period_start",
            "period_end",
            "report_version",
            name="uq_quarterly_report",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "four_week_reports",
        *_report_columns(),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("source_weekly_report_ids", sa.JSON(), nullable=False),
        sa.Column(
            "quarterly_report_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.quarterly_reports.id", ondelete="SET NULL"),
        ),
        sa.UniqueConstraint(
            "manager_id",
            "period_start",
            "period_end",
            "report_version",
            name="uq_four_week_report",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "weekly_reports",
        *_report_columns(),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("source_daily_report_ids", sa.JSON(), nullable=False),
        sa.Column(
            "four_week_report_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.four_week_reports.id", ondelete="SET NULL"),
        ),
        sa.UniqueConstraint(
            "manager_id",
            "period_start",
            "period_end",
            "report_version",
            name="uq_weekly_report",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "daily_reports",
        *_report_columns(),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("source_call_ids", sa.JSON(), nullable=False),
        sa.Column(
            "weekly_report_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.weekly_reports.id", ondelete="SET NULL"),
        ),
        sa.UniqueConstraint(
            "manager_id",
            "report_date",
            "report_version",
            name="uq_daily_report",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "dialogs",
        sa.Column("call_id", sa.String(64), primary_key=True),
        sa.Column("manager_id", sa.String(8), nullable=False),
        sa.Column("manager_name", sa.String(255), nullable=False),
        sa.Column("client_epk", sa.String(128), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("channel", sa.String(64)),
        sa.Column("cleaned_text", sa.Text(), nullable=False),
        sa.Column("participants", sa.JSON(), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("required_analyzers", sa.JSON(), nullable=False),
        sa.Column("analyzer_results", sa.JSON(), nullable=False),
        sa.Column("criteria_results", sa.JSON(), nullable=False),
        sa.Column("analysis_status", sa.String(32), nullable=False),
        sa.Column("analysis_version", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("q_score", sa.Float()),
        sa.Column("critical_violation", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.Column(
            "daily_report_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.daily_reports.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        schema=SCHEMA,
    )
    op.create_table(
        "dialog_utterances",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "call_id",
            sa.String(64),
            sa.ForeignKey(f"{SCHEMA}.dialogs.call_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("speaker_role", sa.String(16), nullable=False),
        sa.Column("speaker_id", sa.Integer()),
        sa.Column("channel", sa.Integer()),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("eou", sa.Boolean(), nullable=False),
        sa.Column("eou_reason", sa.String(64)),
        sa.Column("main_speaker_confidence", sa.Float()),
        sa.Column("emotions", sa.JSON()),
        sa.Column("word_alignments", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "call_id", "sequence_number", name="uq_utterance_call_sequence"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "analysis_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("entity_key", sa.String(255), nullable=False),
        sa.Column("manager_id", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("report_version", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "task_type", "entity_key", "report_version", name="uq_task_entity_version"
        ),
        schema=SCHEMA,
    )

    op.create_index(
        "ix_dialogs_manager_date", "dialogs", ["manager_id", "work_date"], schema=SCHEMA
    )
    op.create_index(
        "ix_dialogs_analysis_status", "dialogs", ["analysis_status"], schema=SCHEMA
    )
    op.create_index(
        "ix_tasks_status_priority",
        "analysis_tasks",
        ["status", "priority", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_daily_manager_date",
        "daily_reports",
        ["manager_id", "report_date"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_weekly_manager_period",
        "weekly_reports",
        ["manager_id", "period_start", "period_end"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_four_week_manager_period",
        "four_week_reports",
        ["manager_id", "period_start", "period_end"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_quarterly_manager_period",
        "quarterly_reports",
        ["manager_id", "period_start", "period_end"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Удаляет таблицы Analyzer в порядке зависимостей."""

    for table in (
        "analysis_tasks",
        "dialog_utterances",
        "dialogs",
        "daily_reports",
        "weekly_reports",
        "four_week_reports",
        "quarterly_reports",
    ):
        op.drop_table(table, schema=SCHEMA)
