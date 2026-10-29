import asyncio
import logging
from datetime import UTC, datetime

from app.agents.gigachat_provider.exceptions import GigaChatError
from app.config import Settings
from app.database.repositories.analysis_task_repository import AnalysisTaskRepository
from app.database.repositories.dialog_repository import DialogRepository
from app.metrics import ANALYZER_JOBS
from app.schemas.entities import AnalysisTaskEntity
from app.services.dialog_analysis.dialog_analysis_orchestrator import (
    DialogAnalysisOrchestrator,
)

logger = logging.getLogger(__name__)


class AnalysisWorker:
    """Разбирает backlog диалогов до текущей рабочей даты."""

    def __init__(
        self,
        settings: Settings,
        tasks: AnalysisTaskRepository,
        dialogs: DialogRepository,
        dialog_orchestrator: DialogAnalysisOrchestrator,
    ) -> None:
        self._settings = settings
        self._tasks = tasks
        self._dialogs = dialogs
        self._dialog_orchestrator = dialog_orchestrator
        self._semaphore = asyncio.Semaphore(settings.dialog_pipeline_concurrency)
        self._claim_limit = min(
            settings.worker_claim_limit,
            settings.dialog_pipeline_concurrency,
        )
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def enqueue(self, call_id: str) -> None:
        await self._tasks.enqueue(call_id)
        logger.info("Task created call_id=%s", call_id)

    async def retry(self, call_id: str) -> bool:
        return await self._tasks.retry(call_id)

    async def run(self) -> None:
        recovered = False
        logger.info(
            "Worker started limit=%s poll=%s",
            self._claim_limit,
            self._settings.worker_poll_interval_seconds,
        )
        while self._running:
            try:
                if not recovered:
                    await self._tasks.recover_processing()
                    recovered = True

                tasks = await self._tasks.claim(
                    self._claim_limit,
                    datetime.now(UTC).date(),
                )
            except Exception as exc:  # noqa: BLE001
                recovered = False
                logger.error("Worker poll failed error=%s", type(exc).__name__)
                await asyncio.sleep(self._settings.worker_poll_interval_seconds)
                continue

            if not tasks:
                await asyncio.sleep(self._settings.worker_poll_interval_seconds)
                continue

            logger.info("Tasks claimed count=%s", len(tasks))
            await asyncio.gather(*(self._run_with_limit(task) for task in tasks))

    async def _run_with_limit(self, task: AnalysisTaskEntity) -> None:
        async with self._semaphore:
            await self._process(task)

    async def _process(self, task: AnalysisTaskEntity) -> None:
        logger.info("Task started call_id=%s", task.call_id)
        try:
            # Успешный orchestrator атомарно создаёт report и удаляет dialog/task.
            await self._dialog_orchestrator.process(task.call_id)
            logger.info("Task completed call_id=%s", task.call_id)
            ANALYZER_JOBS.labels(job_type="dialog", outcome="completed").inc()
        except Exception as exc:  # noqa: BLE001
            error_code = type(exc).__name__
            attempts = exc.attempts if isinstance(exc, GigaChatError) else 0
            await self._tasks.mark_failed(
                task.id,
                error_code=error_code,
                attempt_count=attempts,
            )
            await self._dialogs.mark_failed(task.call_id, error_code)
            logger.error(
                "Task failed call_id=%s error=%s",
                task.call_id,
                error_code,
            )
            ANALYZER_JOBS.labels(job_type="dialog", outcome="failed").inc()
