from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import (
    AnalysisTask,
    DailyReport,
    Dialog,
    FourWeekReport,
    QuarterlyReport,
    WeeklyReport,
)
from app.schemas.entities import AnalysisTaskEntity


class AnalysisTaskRepository:
    """SQL-операции внутренней персистентной очереди Analyzer."""

    async def recover_processing(self) -> None:
        """После рестарта возвращает незавершённую работу в `waiting`."""

        async with session_scope() as session:
            await session.execute(
                update(AnalysisTask)
                .where(AnalysisTask.status == "processing")
                .values(status="waiting")
            )
            await session.execute(
                update(Dialog)
                .where(Dialog.analysis_status == "processing")
                .values(analysis_status="waiting")
            )
            for model in (DailyReport, WeeklyReport, FourWeekReport, QuarterlyReport):
                await session.execute(
                    update(model)
                    .where(model.status == "processing")
                    .values(status="waiting")
                )

    async def enqueue(
        self,
        *,
        task_type: str,
        entity_key: str,
        manager_id: str,
        priority: int,
        report_version: str,
        payload: dict,
    ) -> None:
        """Кладёт идемпотентное задание в очередь."""

        async with session_scope() as session:
            await session.execute(
                insert(AnalysisTask)
                .values(
                    task_type=task_type,
                    entity_key=entity_key,
                    manager_id=manager_id,
                    status="waiting",
                    priority=priority,
                    report_version=report_version,
                    payload=payload,
                )
                .on_conflict_do_nothing(
                    index_elements=["task_type", "entity_key", "report_version"]
                )
            )

    async def claim(self, limit: int) -> list[AnalysisTaskEntity]:
        """Забирает задания через `FOR UPDATE SKIP LOCKED`."""

        async with session_scope() as session:
            tasks = list(
                (
                    await session.scalars(
                        select(AnalysisTask)
                        .where(AnalysisTask.status == "waiting")
                        .order_by(AnalysisTask.priority, AnalysisTask.created_at)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for task in tasks:
                task.status = "processing"
            return [AnalysisTaskEntity.model_validate(task) for task in tasks]

    async def set_status(
        self,
        task_id,
        status: str,
        error_code: str | None = None,
        attempt_count: int = 0,
    ) -> None:
        """Фиксирует завершение либо ошибку задания."""

        async with session_scope() as session:
            task = await session.get(AnalysisTask, task_id, with_for_update=True)
            if task is None:
                return

            task.status = status
            task.error_code = error_code
            task.attempt_count = attempt_count
            task.updated_at = datetime.now(UTC)
