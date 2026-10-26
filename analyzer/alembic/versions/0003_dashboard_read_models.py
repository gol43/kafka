"""Добавляет факты критериев и готовые витрины нового дашборда."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "analyzer_0003"
down_revision = "analyzer_0002"
branch_labels = None
depends_on = None

SCHEMA = "analyzer"


def upgrade() -> None:
    op.add_column("dialogs", sa.Column("client_fio", sa.String(255), nullable=False, server_default=""), schema=SCHEMA)
    op.add_column("dialogs", sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"), schema=SCHEMA)
    op.add_column("dialogs", sa.Column("general_score", sa.Float()), schema=SCHEMA)
    op.add_column("dialogs", sa.Column("deposit_topic", sa.Boolean(), nullable=False, server_default=sa.false()), schema=SCHEMA)
    op.add_column("dialogs", sa.Column("deposit_score", sa.Float()), schema=SCHEMA)
    op.add_column("dialogs", sa.Column("deviations_count", sa.Integer(), nullable=False, server_default="0"), schema=SCHEMA)
    op.add_column("dialogs", sa.Column("dialog_report", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), schema=SCHEMA)

    op.create_table(
        "dialog_metric_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("call_id", sa.String(64), sa.ForeignKey(f"{SCHEMA}.dialogs.call_id", ondelete="CASCADE"), nullable=False),
        sa.Column("manager_id", sa.String(8), nullable=False),
        sa.Column("client_epk", sa.String(128), nullable=False),
        sa.Column("metric_code", sa.String(64), nullable=False),
        sa.Column("metric_title", sa.String(255), nullable=False),
        sa.Column("metric_block", sa.String(32), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("penalty", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text()),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("included_in_analytics", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("call_id", "metric_code", name="uq_dialog_metric"),
        schema=SCHEMA,
    )
    for column in ("call_id", "manager_id", "client_epk", "metric_code", "included_in_analytics", "occurred_at"):
        op.create_index(f"ix_dialog_metric_results_{column}", "dialog_metric_results", [column], schema=SCHEMA)

    op.create_table(
        "manager_metric_daily_stats",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("manager_id", sa.String(8), nullable=False),
        sa.Column("metric_code", sa.String(64), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("communications_count", sa.Integer(), nullable=False),
        sa.Column("completion_percent", sa.Float(), nullable=False),
        sa.UniqueConstraint("manager_id", "metric_code", "stat_date", name="uq_manager_metric_day"),
        schema=SCHEMA,
    )
    for column in ("manager_id", "metric_code", "stat_date"):
        op.create_index(f"ix_manager_metric_daily_stats_{column}", "manager_metric_daily_stats", [column], schema=SCHEMA)

    for table, constraint, columns in (
        ("manager_dashboard_snapshots", "uq_manager_dashboard", ("manager_id", "snapshot_date")),
        ("client_metric_snapshots", "uq_client_metric_snapshot", ("manager_id", "client_epk", "metric_code", "snapshot_date")),
        ("manager_metric_snapshots", "uq_manager_metric_snapshot", ("manager_id", "metric_code", "snapshot_date")),
    ):
        table_columns = [
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("manager_id", sa.String(8), nullable=False),
        ]
        if table == "client_metric_snapshots":
            table_columns.extend([
                sa.Column("client_epk", sa.String(128), nullable=False),
                sa.Column("metric_code", sa.String(64), nullable=False),
            ])
        elif table == "manager_metric_snapshots":
            table_columns.append(sa.Column("metric_code", sa.String(64), nullable=False))
        table_columns.extend([
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
        ])
        if table == "manager_dashboard_snapshots":
            table_columns.append(sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
        table_columns.append(sa.UniqueConstraint(*columns, name=constraint))
        op.create_table(table, *table_columns, schema=SCHEMA)
        op.create_index(f"ix_{table}_manager_id", table, ["manager_id"], schema=SCHEMA)
        op.create_index(f"ix_{table}_snapshot_date", table, ["snapshot_date"], schema=SCHEMA)


def downgrade() -> None:
    for table in ("manager_metric_snapshots", "client_metric_snapshots", "manager_dashboard_snapshots", "manager_metric_daily_stats", "dialog_metric_results"):
        op.drop_table(table, schema=SCHEMA)
    for column in ("dialog_report", "deviations_count", "deposit_score", "deposit_topic", "general_score", "duration_seconds", "client_fio"):
        op.drop_column("dialogs", column, schema=SCHEMA)
