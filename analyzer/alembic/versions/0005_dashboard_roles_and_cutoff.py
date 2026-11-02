"""Добавляет роли, cutoff очереди и структурированные данные dashboard."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "analyzer_0005"
down_revision = "analyzer_0004"
branch_labels = None
depends_on = None

SCHEMA = "analyzer"


def upgrade() -> None:
    op.add_column(
        "analysis_tasks",
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_analysis_tasks_status_claimed",
        "analysis_tasks",
        ["status", "claimed_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_dialog_reports_work_manager",
        "dialog_reports",
        ["work_date", "manager_id"],
        schema=SCHEMA,
    )

    op.add_column(
        "dashboard_aggregates",
        sa.Column(
            "manager_role",
            sa.String(32),
            nullable=False,
            server_default="EFS_VIP_KM",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "dashboard_aggregates",
        sa.Column("dialogs_count", sa.Integer(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.add_column(
        "dashboard_aggregates",
        sa.Column("dialog_score_sum", sa.Float(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.add_column(
        "dashboard_aggregates",
        sa.Column("dialog_score_count", sa.Integer(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    for column in ("daily_metrics", "rolling_30_metrics", "quarter_score_data", "month_score_data"):
        op.add_column(
            "dashboard_aggregates",
            sa.Column(
                column,
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            schema=SCHEMA,
        )
    op.add_column(
        "dashboard_aggregates",
        sa.Column(
            "daily_risks",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "dashboard_aggregates",
        sa.Column("weekly_metrics", postgresql.JSONB()),
        schema=SCHEMA,
    )
    op.execute(
        """
        UPDATE analyzer.dashboard_aggregates
        SET dialogs_count = COALESCE((data #>> '{daily,dialogsCount}')::integer, 0),
            dialog_score_sum = COALESCE((data #>> '{daily,dialogScoreSum}')::double precision, 0),
            dialog_score_count = COALESCE((data #>> '{daily,dialogScoreCount}')::integer, 0),
            daily_metrics = COALESCE(data #> '{daily,metrics}', '{}'::jsonb),
            daily_risks = COALESCE(data #> '{daily,risks}', '[]'::jsonb),
            rolling_30_metrics = COALESCE(data #> '{rolling30,metrics}', '{}'::jsonb),
            weekly_metrics = CASE
                WHEN COALESCE((data #>> '{week,completed}')::boolean, false)
                THEN data -> 'week'
                ELSE NULL
            END,
            quarter_score_data = COALESCE(data -> 'quarter', '{}'::jsonb),
            month_score_data = COALESCE(data -> 'month', '{}'::jsonb)
        """
    )
    op.drop_column("dashboard_aggregates", "data", schema=SCHEMA)
    op.create_index(
        "ix_dashboard_aggregates_manager_date",
        "dashboard_aggregates",
        ["manager_id", "aggregate_date"],
        schema=SCHEMA,
    )
    op.alter_column(
        "dashboard_aggregates",
        "manager_role",
        server_default=None,
        schema=SCHEMA,
    )

    op.add_column(
        "dashboard_snapshots",
        sa.Column(
            "manager_role",
            sa.String(32),
            nullable=False,
            server_default="EFS_VIP_KM",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "dashboard_snapshots",
        sa.Column("source_date", sa.Date()),
        schema=SCHEMA,
    )
    op.add_column(
        "dashboard_snapshots",
        sa.Column(
            "carried_forward",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema=SCHEMA,
    )
    op.execute(
        "UPDATE analyzer.dashboard_snapshots SET source_date = report_date"
    )
    op.alter_column(
        "dashboard_snapshots",
        "source_date",
        nullable=False,
        schema=SCHEMA,
    )
    op.alter_column("dashboard_snapshots", "manager_role", server_default=None, schema=SCHEMA)
    op.alter_column("dashboard_snapshots", "carried_forward", server_default=None, schema=SCHEMA)


def downgrade() -> None:
    op.add_column(
        "dashboard_aggregates",
        sa.Column(
            "data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema=SCHEMA,
    )
    op.execute(
        """
        UPDATE analyzer.dashboard_aggregates
        SET data = jsonb_build_object(
            'daily', jsonb_build_object(
                'dialogsCount', dialogs_count,
                'dialogScoreSum', dialog_score_sum,
                'dialogScoreCount', dialog_score_count,
                'metrics', daily_metrics,
                'risks', daily_risks
            ),
            'rolling30', jsonb_build_object('metrics', rolling_30_metrics),
            'quarter', quarter_score_data,
            'week', COALESCE(weekly_metrics, '{"completed": false}'::jsonb),
            'month', month_score_data
        )
        """
    )
    op.drop_index(
        "ix_dashboard_aggregates_manager_date",
        table_name="dashboard_aggregates",
        schema=SCHEMA,
    )
    for column in (
        "month_score_data",
        "quarter_score_data",
        "weekly_metrics",
        "rolling_30_metrics",
        "daily_risks",
        "daily_metrics",
        "dialog_score_count",
        "dialog_score_sum",
        "dialogs_count",
        "manager_role",
    ):
        op.drop_column("dashboard_aggregates", column, schema=SCHEMA)
    for column in ("carried_forward", "source_date", "manager_role"):
        op.drop_column("dashboard_snapshots", column, schema=SCHEMA)

    op.drop_index(
        "ix_dialog_reports_work_manager",
        table_name="dialog_reports",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_analysis_tasks_status_claimed",
        table_name="analysis_tasks",
        schema=SCHEMA,
    )
    op.drop_column("analysis_tasks", "claimed_at", schema=SCHEMA)
