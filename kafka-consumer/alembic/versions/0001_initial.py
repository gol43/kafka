"""Initial Kafka schema."""

import sqlalchemy as sa

from alembic import op

revision = "kafka_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS kafka")
    op.create_table(
        "dialog_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("call_id", sa.String(64), nullable=False),
        sa.Column("part", sa.BigInteger(), nullable=False),
        sa.Column("is_last", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("call_id", "part", name="uq_dialog_chunks_call_part"),
        schema="kafka",
    )
    op.create_index(
        "ix_dialog_chunks_call_part",
        "dialog_chunks",
        ["call_id", "part"],
        schema="kafka",
    )
    op.create_table(
        "dialog_state",
        sa.Column("call_id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="collecting"),
        sa.Column("last_part", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="kafka",
    )


def downgrade() -> None:
    op.drop_table("dialog_state", schema="kafka")
    op.drop_index(
        "ix_dialog_chunks_call_part", table_name="dialog_chunks", schema="kafka"
    )
    op.drop_table("dialog_chunks", schema="kafka")
