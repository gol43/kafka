import asyncio
from datetime import UTC, date, datetime, time

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings
from app.database.repositories.analysis_task_repository import AnalysisTaskRepository
from app.database.repositories.dialog_repository import DialogRepository
from app.services.dashboard.dashboard_builder import DashboardBuilder


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
        while await self._dialogs.pending_before_cutoff(target, cutoff):
            await asyncio.sleep(self._settings.dashboard_wait_interval_seconds)

        await self._builder.rebuild(target)
        now = datetime.now(UTC)
        await self._dialogs.cleanup_expired(now)
        await self._tasks.cleanup_expired(now)
