"""Initial cleaner schema."""

import sqlalchemy as sa

from alembic import op

revision = "cleaner_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS cleaner")
    op.create_table(
        "cleaner_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("call_id", sa.String(64), nullable=False, unique=True),
        sa.Column("encrypted", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="waiting"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="cleaner",
    )
    op.create_index(
        "ix_cleaner_jobs_status_created",
        "cleaner_jobs",
        ["status", "created_at"],
        schema="cleaner",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cleaner_jobs_status_created", table_name="cleaner_jobs", schema="cleaner"
    )
    op.drop_table("cleaner_jobs", schema="cleaner")
