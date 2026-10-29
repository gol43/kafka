from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import AnalysisTask, Dialog
from app.schemas.entities import AnalysisTaskEntity


class AnalysisTaskRepository:
    """Персистентная очередь анализа диалогов."""

    def __init__(self, ttl_days: int) -> None:
        self._ttl = timedelta(days=ttl_days)

    async def recover_processing(self) -> None:
        """После рестарта возвращает незавершённые задания в waiting."""

        async with session_scope() as session:
            await session.execute(
                update(AnalysisTask)
                .where(AnalysisTask.status == "processing")
                .values(status="waiting")
            )
            await session.execute(
                update(Dialog)
                .where(Dialog.status == "processing")
                .values(status="waiting")
            )

    async def enqueue(self, call_id: str) -> None:
        now = datetime.now(UTC)
        async with session_scope() as session:
            await session.execute(
                insert(AnalysisTask)
                .values(
                    call_id=call_id,
                    status="waiting",
                    expires_at=now + self._ttl,
                )
                .on_conflict_do_nothing(index_elements=["call_id"])
            )

    async def claim(self, limit: int, current_work_date: date) -> list[AnalysisTaskEntity]:
        """Берёт backlog до текущей рабочей даты через SKIP LOCKED."""

        async with session_scope() as session:
            tasks = list(
                (
                    await session.scalars(
                        select(AnalysisTask)
                        .join(Dialog, Dialog.call_id == AnalysisTask.call_id)
                        .where(
                            AnalysisTask.status == "waiting",
                            Dialog.work_date <= current_work_date,
                        )
                        .order_by(Dialog.work_date, AnalysisTask.created_at)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            call_ids = [task.call_id for task in tasks]
            for task in tasks:
                task.status = "processing"
                task.error_code = None
            if call_ids:
                await session.execute(
                    update(Dialog)
                    .where(Dialog.call_id.in_(call_ids))
                    .values(status="processing", error_code=None)
                )
            return [AnalysisTaskEntity.model_validate(task) for task in tasks]

    async def mark_failed(
        self,
        task_id,
        *,
        error_code: str,
        attempt_count: int,
    ) -> None:
        async with session_scope() as session:
            task = await session.get(AnalysisTask, task_id, with_for_update=True)
            if task:
                task.status = "failed"
                task.error_code = error_code
                task.attempt_count = attempt_count

    async def retry(self, call_id: str) -> bool:
        """Возвращает failed-задание в очередь для ручной проверки."""

        async with session_scope() as session:
            task = await session.scalar(
                select(AnalysisTask)
                .where(AnalysisTask.call_id == call_id)
                .with_for_update()
            )
            dialog = await session.get(Dialog, call_id, with_for_update=True)
            if task is None or dialog is None:
                return False
            task.status = "waiting"
            task.error_code = None
            dialog.status = "waiting"
            dialog.error_code = None
            return True

    async def cleanup_expired(self, now: datetime) -> None:
        async with session_scope() as session:
            await session.execute(
                delete(AnalysisTask).where(AnalysisTask.expires_at < now)
            )
