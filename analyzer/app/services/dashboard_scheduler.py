from datetime import UTC, date, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings
from app.services.dashboard_builder import DashboardBuilder


class DashboardScheduler:
    """Ежедневно формирует готовые витрины по завершённому предыдущему дню."""

    def __init__(self, settings: Settings, builder: DashboardBuilder) -> None:
        self._settings = settings
        self._builder = builder
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

    async def rebuild(self, snapshot_date: date | None = None) -> None:
        target = snapshot_date or (datetime.now(UTC).date() - timedelta(days=1))
        await self._builder.rebuild(target)
