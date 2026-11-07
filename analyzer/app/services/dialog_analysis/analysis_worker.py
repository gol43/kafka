import asyncio
from datetime import UTC, datetime, timedelta
import logging

from app.agents.gigachat_provider.exceptions import GigaChatError
from app.config import Settings
from app.database.repositories.analysis_task_repository import AnalysisTaskRepository
from app.database.repositories.dialog_repository import DialogRepository
from app.metrics import ANALYZER_JOBS
from app.exceptions import AnalysisDeadlineExceededError
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

    async def retry(self, call_id: str) -> bool:
        return await self._tasks.retry(call_id)

    async def run(self) -> None:
        next_recovery_at = 0.0
        logger.info(
            "Worker started limit=%s poll=%s",
            self._claim_limit,
            self._settings.worker_poll_interval_seconds,
        )
        while self._running:
            try:
                loop_time = asyncio.get_running_loop().time()
                if loop_time >= next_recovery_at:
                    stale_before = datetime.now(UTC) - timedelta(
                        seconds=self._settings.worker_stale_task_seconds
                    )
                    await self._tasks.recover_processing(stale_before)
                    next_recovery_at = (
                        loop_time
                        + self._settings.worker_recovery_interval_seconds
                    )

                now = datetime.now(UTC)
                tasks = await self._tasks.claim(
                    self._claim_limit,
                    now.date(),
                    now,
                    self._settings.dashboard_cron_hour_utc,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Worker poll failed error=%s", type(exc).__name__)
                await asyncio.sleep(self._settings.worker_poll_interval_seconds)
                continue

            if not tasks:
                await asyncio.sleep(self._settings.worker_poll_interval_seconds)
                continue

            logger.info("Tasks claimed count=%s", len(tasks))
            async with asyncio.TaskGroup() as group:
                for task in tasks:
                    group.create_task(self._run_with_limit(task))

    async def _run_with_limit(self, task: AnalysisTaskEntity) -> None:
        async with self._semaphore:
            await self._process(task)

    async def _process(self, task: AnalysisTaskEntity) -> None:
        logger.info("Task started call_id=%s", task.call_id)
        try:
            await self._dialog_orchestrator.process(task.call_id)
            logger.info("Task completed call_id=%s", task.call_id)
            ANALYZER_JOBS.labels(job_type="dialog", outcome="completed").inc()
        except AnalysisDeadlineExceededError:
            logger.info("Task closed by cutoff call_id=%s", task.call_id)
            ANALYZER_JOBS.labels(job_type="dialog", outcome="not_analyzed").inc()
        except Exception as exc:  # noqa: BLE001
            error_code = type(exc).__name__
            attempts = exc.attempts if isinstance(exc, GigaChatError) else 0
            await self._tasks.mark_failed(
                task.id,
                error_code=error_code,
                attempt_count=attempts,
            )
            await self._dialogs.mark_failed(task.call_id, error_code)
            logger.error(f'Task error: {exc}', exc_info=True)
            logger.error("Task failed call_id=%s error=%s", task.call_id, error_code)
            ANALYZER_JOBS.labels(job_type="dialog", outcome="failed").inc()
