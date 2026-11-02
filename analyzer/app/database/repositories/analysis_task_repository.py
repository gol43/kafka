from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select, update
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
                .values(status="waiting", claimed_at=None)
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

    async def claim(
        self,
        limit: int,
        current_work_date: date,
        now: datetime,
        cutoff_hour_utc: int,
    ) -> list[AnalysisTaskEntity]:
        """Берёт backlog до текущей рабочей даты через SKIP LOCKED."""

        latest_date = current_work_date
        if now.hour >= cutoff_hour_utc:
            latest_date -= timedelta(days=1)

        async with session_scope() as session:
            tasks = list(
                (
                    await session.scalars(
                        select(AnalysisTask)
                        .join(Dialog, Dialog.call_id == AnalysisTask.call_id)
                        .where(
                            AnalysisTask.status == "waiting",
                            Dialog.work_date <= latest_date,
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
                task.claimed_at = now
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
            task.claimed_at = None
            dialog.status = "waiting"
            dialog.error_code = None
            return True

    async def rollover_waiting(
        self,
        work_date: date,
        next_date: date,
        batch_size: int,
    ) -> int:
        """Переносит не начатые к cutoff диалоги на следующий рабочий день."""

        async with session_scope() as session:
            rows = list(
                (
                    await session.scalars(
                        select(AnalysisTask)
                        .join(Dialog, Dialog.call_id == AnalysisTask.call_id)
                        .where(
                            AnalysisTask.status == "waiting",
                            Dialog.work_date == work_date,
                        )
                        .limit(batch_size)
                        .with_for_update()
                    )
                ).all()
            )
            call_ids = [row.call_id for row in rows]
            if call_ids:
                await session.execute(
                    update(Dialog)
                    .where(Dialog.call_id.in_(call_ids))
                    .values(work_date=next_date)
                )
            return len(call_ids)

    async def processing_before_cutoff(
        self,
        work_date: date,
        cutoff: datetime,
    ) -> int:
        """Считает только задания, которые реально стартовали до cutoff."""

        async with session_scope() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(AnalysisTask)
                    .join(Dialog, Dialog.call_id == AnalysisTask.call_id)
                    .where(
                        AnalysisTask.status == "processing",
                        AnalysisTask.claimed_at < cutoff,
                        Dialog.work_date == work_date,
                    )
                )
                or 0
            )

    async def cleanup_expired(self, now: datetime, batch_size: int) -> None:
        while True:
            async with session_scope() as session:
                ids = (
                    select(AnalysisTask.id)
                    .where(AnalysisTask.expires_at < now)
                    .limit(batch_size)
                )
                result = await session.execute(
                    delete(AnalysisTask)
                    .where(AnalysisTask.id.in_(ids))
                    .returning(AnalysisTask.id)
                )
                deleted = len(result.scalars().all())
            if deleted < batch_size:
                return
