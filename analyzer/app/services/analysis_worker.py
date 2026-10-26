import asyncio
import logging
from app.agents.gigachat_provider.exceptions import GigaChatError
from app.config import Settings
from app.database.repositories.analysis_task_repository import AnalysisTaskRepository
from app.database.repositories.dialog_repository import DialogRepository
from app.metrics import ANALYZER_JOBS
from app.schemas.entities import AnalysisTaskEntity
from app.services.dialog_analysis_orchestrator import DialogAnalysisOrchestrator

logger = logging.getLogger(__name__)

TASK_PRIORITY = {
    "dialog": 10,
}


class AnalysisWorker:
    """Разбирает персистентную очередь заданий Analyzer.

    Параллельность pipeline отделена от лимита HTTP-запросов GigaChat.
    GigaChatProvider применяет собственный общий semaphore к каждому запросу.
    """

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
        """Останавливает получение новых заданий."""

        self._running = False

    async def enqueue(
        self,
        task_type: str,
        entity_key: str,
        manager_id: str,
        payload: dict | None = None,
    ) -> None:
        """Добавляет идемпотентное задание в очередь PostgreSQL."""

        await self._tasks.enqueue(
            task_type=task_type,
            entity_key=entity_key,
            manager_id=manager_id,
            priority=TASK_PRIORITY[task_type],
            report_version=self._settings.report_version,
            payload=payload or {},
        )
        logger.info("Task created type=%s key=%s", task_type, entity_key)

    async def run(self) -> None:
        """Бесконечно опрашивает БД и обрабатывает доступные задания."""

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

                tasks = await self._tasks.claim(self._claim_limit)
            except Exception as exc:  # noqa: BLE001
                recovered = False
                logger.error("Worker poll failed error=%s", type(exc).__name__)
                await asyncio.sleep(self._settings.worker_poll_interval_seconds)
                continue

            if not tasks:
                await asyncio.sleep(self._settings.worker_poll_interval_seconds)
                continue
            logger.info(
                "Tasks claimed count=%s limit=%s", len(tasks), self._claim_limit
            )
            await asyncio.gather(*(self._run_with_limit(task) for task in tasks))

    async def _run_with_limit(self, task: AnalysisTaskEntity) -> None:
        async with self._semaphore:
            await self._process(task)

    async def _process(self, task: AnalysisTaskEntity) -> None:
        logger.info("Task started type=%s key=%s", task.task_type, task.entity_key)
        try:
            if task.task_type != "dialog":
                raise ValueError(f"Неизвестный тип задания: {task.task_type}")
            await self._dialog_orchestrator.process(task.entity_key)

            await self._tasks.set_status(task.id, "completed")
            logger.info(
                "Task completed type=%s key=%s", task.task_type, task.entity_key
            )
            ANALYZER_JOBS.labels(
                job_type=task.task_type,
                outcome="completed",
            ).inc()
        # Граница задания обязана сохранить любую ошибку, но worker продолжает цикл.
        except Exception as exc:  # noqa: BLE001
            error_code = type(exc).__name__
            attempts = exc.attempts if isinstance(exc, GigaChatError) else 0

            await self._tasks.set_status(
                task.id,
                "failed",
                error_code=error_code,
                attempt_count=attempts,
            )
            await self._mark_result_failed(task, error_code)
            logger.error(
                "Task failed type=%s key=%s error=%s",
                task.task_type,
                task.entity_key,
                error_code,
            )
            ANALYZER_JOBS.labels(
                job_type=task.task_type,
                outcome="failed",
            ).inc()

    async def _mark_result_failed(
        self,
        task: AnalysisTaskEntity,
        error_code: str,
    ) -> None:
        await self._dialogs.mark_failed(task.entity_key, error_code)
