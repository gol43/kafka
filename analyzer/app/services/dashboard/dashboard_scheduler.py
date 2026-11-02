import asyncio
from datetime import UTC, date, datetime, time
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings
from app.database.repositories.analysis_task_repository import AnalysisTaskRepository
from app.database.repositories.dialog_repository import DialogRepository
from app.services.dashboard.dashboard_builder import DashboardBuilder
from app.services.dialog_analysis.calendar_policy import next_work_date

logger = logging.getLogger(__name__)


class DashboardScheduler:
    """После cutoff ждёт terminal-задачи и строит витрину текущего дня."""

    def __init__(
        self,
        settings: Settings,
        builder: DashboardBuilder,
        dialogs: DialogRepository,
        tasks: AnalysisTaskRepository,
    ) -> None:
        self._settings = settings
        self._builder = builder
        self._dialogs = dialogs
        self._tasks = tasks
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        if self._settings.dashboard_enabled:
            self._scheduler.add_job(
                self.rebuild,
                "cron",
                hour=self._settings.dashboard_cron_hour_utc,
                minute=0,
                id="dashboard",
                max_instances=1,
                coalesce=True,
            )
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def rebuild(self, report_date: date | None = None) -> None:
        target = report_date or datetime.now(UTC).date()
        if target.weekday() >= 5:
            return

        cutoff = datetime.combine(
            target,
            time(hour=self._settings.dashboard_cron_hour_utc),
            tzinfo=UTC,
        )
        moved_total = 0
        while True:
            moved = await self._tasks.rollover_waiting(
                target,
                next_work_date(target),
                self._settings.dashboard_cleanup_batch_size,
            )
            moved_total += moved
            if moved < self._settings.dashboard_cleanup_batch_size:
                break
        logger.info("Waiting moved date=%s count=%s", target, moved_total)

        while True:
            processing = await self._tasks.processing_before_cutoff(target, cutoff)
            if not processing:
                break
            logger.info("Dashboard waits tasks count=%s", processing)
            await asyncio.sleep(self._settings.dashboard_wait_interval_seconds)

        await self._builder.rebuild(target)
        now = datetime.now(UTC)
        await self._dialogs.cleanup_expired(
            now,
            self._settings.dashboard_cleanup_batch_size,
        )
        await self._tasks.cleanup_expired(
            now,
            self._settings.dashboard_cleanup_batch_size,
        )
