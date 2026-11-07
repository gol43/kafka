import asyncio
from datetime import UTC, date, datetime, time, timedelta
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings
from app.database.repositories.analysis_task_repository import AnalysisTaskRepository
from app.database.repositories.dashboard_repository import DashboardRepository
from app.database.repositories.dialog_repository import DialogRepository
from app.services.dashboard.dashboard_builder import DashboardBuilder

logger = logging.getLogger(__name__)


class DashboardScheduler:
    """После cutoff ждёт terminal-задачи и строит витрину текущего дня."""

    def __init__(
        self,
        settings: Settings,
        builder: DashboardBuilder,
        dashboards: DashboardRepository,
        dialogs: DialogRepository,
        tasks: AnalysisTaskRepository,
    ) -> None:
        self._settings = settings
        self._builder = builder
        self._dashboards = dashboards
        self._dialogs = dialogs
        self._tasks = tasks
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        if self._settings.dashboard_enabled:
            self._scheduler.add_job(
                self.rebuild,
                trigger="cron",
                hour=self._settings.dashboard_cron_hour_utc,
                minute=0,
                id="dashboard",
                max_instances=1,
                coalesce=True,
            )
        self._scheduler.add_job(
            self.cleanup_expired,
            trigger="interval",
            minutes=self._settings.data_cleanup_interval_minutes,
            id="data-cleanup",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(UTC),
        )
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def rebuild(self, report_date: date | None = None) -> None:
        target = report_date or datetime.now(UTC).date()
        if target.weekday() >= 5:
            return

        async with self._dashboards.build_lock() as acquired:
            if not acquired:
                logger.info("Dashboard build skipped another instance is active")
                return
            await self._rebuild_locked(target)

    async def _rebuild_locked(self, target: date) -> None:
        cutoff = datetime.combine(
            target,
            time(hour=self._settings.dashboard_cron_hour_utc),
            tzinfo=UTC,
        )

        processing = await self._tasks.processing_before_cutoff(target, cutoff)
        now = datetime.now(UTC)
        deadline = cutoff + timedelta(
            seconds=self._settings.dashboard_analysis_grace_seconds
        )
        if processing and now < deadline:
            wait_seconds = (deadline - now).total_seconds()
            logger.info(
                "Dashboard delayed processing=%s seconds=%s",
                processing,
                int(wait_seconds),
            )
            await asyncio.sleep(wait_seconds)

        unfinished = await self._tasks.close_unfinished(target)
        if unfinished:
            logger.warning(
                "Dialogs closed without analysis date=%s count=%s",
                target,
                unfinished,
            )

        await self._builder.rebuild(target)

    async def cleanup_expired(self) -> None:
        now = datetime.now(UTC)
        await self._dialogs.cleanup_expired(now, self._settings.dashboard_cleanup_batch_size)
        await self._tasks.cleanup_expired(now, self._settings.dashboard_cleanup_batch_size)
        await self._dashboards.cleanup_expired(
            now,
            self._settings.dashboard_cleanup_batch_size,
        )
