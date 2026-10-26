from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import CleanerJob


class CleanerJobRepository:
    """Owns all access to the Data Cleaner job table."""

    async def enqueue(self, call_id: str, encrypted: bool, payload: bytes) -> None:
        async with session_scope() as session:
            await session.execute(
                insert(CleanerJob)
                .values(call_id=call_id, encrypted=encrypted, payload=payload)
                .on_conflict_do_nothing(index_elements=["call_id"])
            )

    async def recover_processing(self) -> None:
        async with session_scope() as session:
            await session.execute(
                update(CleanerJob)
                .where(CleanerJob.status == "processing")
                .values(status="waiting")
            )

    async def claim(self, limit: int) -> list[CleanerJob]:
        async with session_scope() as session:
            jobs = list(
                (
                    await session.scalars(
                        select(CleanerJob)
                        .where(CleanerJob.status == "waiting")
                        .order_by(CleanerJob.created_at)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )

            for job in jobs:
                job.status = "processing"

            return jobs

    async def delete(self, job_id) -> None:
        async with session_scope() as session:
            await session.execute(delete(CleanerJob).where(CleanerJob.id == job_id))
