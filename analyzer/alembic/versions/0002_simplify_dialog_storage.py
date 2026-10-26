"""Упрощает хранение диалога и переводит JSON-колонки в JSONB."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "analyzer_0002"
down_revision = "analyzer_0001"
branch_labels = None
depends_on = None

SCHEMA = "analyzer"


def _to_jsonb(table: str, column: str) -> None:
    op.alter_column(
        table,
        column,
        schema=SCHEMA,
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(),
        postgresql_using=f"{column}::jsonb",
    )


def _to_json(table: str, column: str) -> None:
    op.alter_column(
        table,
        column,
        schema=SCHEMA,
        existing_type=postgresql.JSONB(),
        type_=sa.JSON(),
        postgresql_using=f"{column}::json",
    )


def upgrade() -> None:
    op.add_column(
        "dialogs",
        sa.Column(
            "dialog_data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=SCHEMA,
    )

    op.execute(
        """
        UPDATE analyzer.dialogs AS dialog
        SET dialog_data = source.items
        FROM (
            SELECT
                call_id,
                jsonb_agg(
                    jsonb_build_object(
                        'sequence_number', sequence_number,
                        'speaker_role', speaker_role,
                        'speaker_id', speaker_id,
                        'channel', channel,
                        'text', text,
                        'start_ms', start_ms,
                        'end_ms', end_ms,
                        'eou', eou,
                        'eou_reason', eou_reason,
                        'main_speaker_confidence', main_speaker_confidence,
                        'emotions', emotions::jsonb,
                        'word_alignments', word_alignments::jsonb
                    ) ORDER BY sequence_number
                ) AS items
            FROM analyzer.dialog_utterances
            GROUP BY call_id
        ) AS source
        WHERE source.call_id = dialog.call_id
        """
    )

    op.execute(
        """
        UPDATE analyzer.dialogs
        SET analyzer_results = CASE
            WHEN analyzer_results::jsonb ? 'prompt'
                THEN analyzer_results
            ELSE (
                analyzer_results::jsonb
                || jsonb_build_object(
                    'prompt',
                    jsonb_build_object('criteria', criteria_results::jsonb)
                )
            )::json
        END
        """
    )

    for table, columns in {
        "dialogs": ("required_analyzers", "analyzer_results"),
        "analysis_tasks": ("payload",),
        "daily_reports": ("details", "source_call_ids"),
        "weekly_reports": ("details", "source_daily_report_ids"),
        "four_week_reports": ("details", "source_weekly_report_ids"),
        "quarterly_reports": ("details", "source_four_week_report_ids"),
    }.items():
        for column in columns:
            _to_jsonb(table, column)

    op.alter_column(
        "dialogs",
        "analyzer_results",
        new_column_name="analysis_results",
        schema=SCHEMA,
    )
    op.alter_column(
        "dialogs",
        "analysis_version",
        new_column_name="criteria_version",
        schema=SCHEMA,
    )
    op.alter_column(
        "dialogs",
        "model_version",
        new_column_name="model_name",
        schema=SCHEMA,
    )
    op.alter_column(
        "dialogs",
        "dialog_data",
        server_default=None,
        schema=SCHEMA,
    )

    op.drop_column("dialogs", "participants", schema=SCHEMA)
    op.drop_column("dialogs", "source_metadata", schema=SCHEMA)
    op.drop_column("dialogs", "criteria_results", schema=SCHEMA)
    op.drop_table("dialog_utterances", schema=SCHEMA)


def downgrade() -> None:
    op.create_table(
        "dialog_utterances",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "call_id",
            sa.String(64),
            sa.ForeignKey("analyzer.dialogs.call_id", ondelete="CASCADE"),
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
            "call_id",
            "sequence_number",
            name="uq_utterance_call_sequence",
        ),
        schema=SCHEMA,
    )

    op.add_column(
        "dialogs",
        sa.Column("participants", sa.JSON(), nullable=False, server_default="[]"),
        schema=SCHEMA,
    )
    op.add_column(
        "dialogs",
        sa.Column("source_metadata", sa.JSON(), nullable=False, server_default="{}"),
        schema=SCHEMA,
    )
    op.add_column(
        "dialogs",
        sa.Column("criteria_results", sa.JSON(), nullable=False, server_default="[]"),
        schema=SCHEMA,
    )
    op.execute(
        """
        UPDATE analyzer.dialogs
        SET criteria_results = COALESCE(
            analysis_results #> '{prompt,criteria}',
            '[]'::jsonb
        )::json
        """
    )

    op.alter_column(
        "dialogs",
        "analysis_results",
        new_column_name="analyzer_results",
        schema=SCHEMA,
    )
    op.alter_column(
        "dialogs",
        "criteria_version",
        new_column_name="analysis_version",
        schema=SCHEMA,
    )
    op.alter_column(
        "dialogs",
        "model_name",
        new_column_name="model_version",
        schema=SCHEMA,
    )

    for table, columns in {
        "dialogs": ("required_analyzers", "analyzer_results"),
        "analysis_tasks": ("payload",),
        "daily_reports": ("details", "source_call_ids"),
        "weekly_reports": ("details", "source_daily_report_ids"),
        "four_week_reports": ("details", "source_weekly_report_ids"),
        "quarterly_reports": ("details", "source_four_week_report_ids"),
    }.items():
        for column in columns:
            _to_json(table, column)

    op.drop_column("dialogs", "dialog_data", schema=SCHEMA)
