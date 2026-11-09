import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database.models import Base, SCHEMA

settings = get_settings()

PERFORMANCE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_dialogs_expires_at "
    f'ON "{SCHEMA}".dialogs (expires_at)',
    "CREATE INDEX IF NOT EXISTS ix_dialogs_unfinished_work_date "
    f'ON "{SCHEMA}".dialogs (work_date, call_id) '
    "WHERE status IN ('waiting', 'processing')",
    "CREATE INDEX IF NOT EXISTS ix_analysis_tasks_waiting_created "
    f'ON "{SCHEMA}".analysis_tasks (created_at) WHERE status = \'waiting\'',
    "CREATE INDEX IF NOT EXISTS ix_analysis_tasks_processing_claimed "
    f'ON "{SCHEMA}".analysis_tasks (claimed_at) WHERE status = \'processing\'',
    "CREATE INDEX IF NOT EXISTS ix_analysis_tasks_expires_at "
    f'ON "{SCHEMA}".analysis_tasks (expires_at)',
    "CREATE INDEX IF NOT EXISTS ix_dialog_reports_manager_occurred "
    f'ON "{SCHEMA}".dialog_reports (manager_id, occurred_at)',
    "CREATE INDEX IF NOT EXISTS ix_dialog_reports_expires_at "
    f'ON "{SCHEMA}".dialog_reports (expires_at)',
    "CREATE INDEX IF NOT EXISTS ix_dashboard_aggregates_expires_at "
    f'ON "{SCHEMA}".dashboard_aggregates (expires_at)',
    "CREATE INDEX IF NOT EXISTS ix_dashboard_snapshots_expires_at "
    f'ON "{SCHEMA}".dashboard_snapshots (expires_at)',
)

SCHEMA_UPDATES = (
    f'ALTER TABLE IF EXISTS "{SCHEMA}".dialogs '
    "ADD COLUMN IF NOT EXISTS client_fio VARCHAR(256)",
    f'ALTER TABLE IF EXISTS "{SCHEMA}".dialog_reports '
    "ADD COLUMN IF NOT EXISTS client_fio VARCHAR(256)",
    f'ALTER TABLE IF EXISTS "{SCHEMA}".dialogs '
    "ADD COLUMN IF NOT EXISTS source_payload JSONB",
    f'ALTER TABLE IF EXISTS "{SCHEMA}".dialog_reports '
    "ADD COLUMN IF NOT EXISTS source_payload JSONB",
    f'UPDATE "{SCHEMA}".dialogs SET client_fio = \'\' WHERE client_fio IS NULL',
    f'UPDATE "{SCHEMA}".dialog_reports SET client_fio = \'\' WHERE client_fio IS NULL',
    f'UPDATE "{SCHEMA}".dialogs SET source_payload = \'{{}}\'::jsonb '
    "WHERE source_payload IS NULL",
    f'UPDATE "{SCHEMA}".dialog_reports SET source_payload = \'{{}}\'::jsonb '
    "WHERE source_payload IS NULL",
    f'ALTER TABLE IF EXISTS "{SCHEMA}".dialogs '
    "ALTER COLUMN client_fio SET DEFAULT '', ALTER COLUMN client_fio SET NOT NULL",
    f'ALTER TABLE IF EXISTS "{SCHEMA}".dialog_reports '
    "ALTER COLUMN client_fio SET DEFAULT '', ALTER COLUMN client_fio SET NOT NULL",
    f'ALTER TABLE IF EXISTS "{SCHEMA}".dialogs '
    "ALTER COLUMN source_payload SET DEFAULT '{}', ALTER COLUMN source_payload SET NOT NULL",
    f'ALTER TABLE IF EXISTS "{SCHEMA}".dialog_reports '
    "ALTER COLUMN source_payload SET DEFAULT '{}', ALTER COLUMN source_payload SET NOT NULL",
)

engine = create_async_engine(
    settings.postgres_dsn,
    pool_pre_ping=True,
    pool_size=settings.postgres_pool_size,
    max_overflow=settings.postgres_max_overflow,
    pool_recycle=settings.postgres_pool_recycle_seconds,
    connect_args={"statement_cache_size": 0},
    json_serializer=lambda value: json.dumps(value, ensure_ascii=False),
)

session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session, session.begin():
        yield session


async def check_database() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


async def initialize_database() -> None:
    if not settings.database_auto_create_schema:
        return

    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
        await connection.run_sync(Base.metadata.create_all)
        for statement in SCHEMA_UPDATES:
            await connection.execute(text(statement))
        for statement in PERFORMANCE_INDEXES:
            await connection.execute(text(statement))
