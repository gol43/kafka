from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings
from app.database.repositories.report_repository import ReportRepository
from app.services.analysis_worker import AnalysisWorker


class ReportScheduler:
    """По расписанию создаёт задания для агрегированных отчётов."""

    def __init__(
        self,
        settings: Settings,
        repository: ReportRepository,
        worker: AnalysisWorker,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._worker = worker
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    def start(self) -> None:
        """Регистрирует только ежедневное и недельное расписания."""

        if self._settings.daily_report_enabled:
            self._scheduler.add_job(
                self.enqueue_daily,
                "cron",
                day_of_week="mon-fri",
                hour=self._settings.daily_report_cron_hour_utc,
                minute=0,
                id="daily",
                max_instances=1,
                coalesce=True,
            )

        if self._settings.weekly_report_enabled:
            self._scheduler.add_job(
                self.enqueue_weekly,
                "cron",
                day_of_week=self._settings.weekly_report_cron_day,
                hour=self._settings.weekly_report_cron_hour_utc,
                minute=0,
                id="weekly",
                max_instances=1,
                coalesce=True,
            )

        self._scheduler.start()

    def shutdown(self) -> None:
        """Останавливает APScheduler без ожидания активных заданий."""

        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def enqueue_daily(self, work_date: date | None = None) -> None:
        """Ставит дневные отчёты всех активных менеджеров."""

        target_date = work_date or date.today()
        managers = await self._repository.managers_with_completed_dialogs(target_date)

        for manager_id in managers:
            await self._worker.enqueue(
                "daily",
                f"{manager_id}:{target_date}",
                manager_id,
                {
                    "period_start": str(target_date),
                    "period_end": str(target_date),
                },
            )

    async def enqueue_weekly(self, end: date | None = None) -> None:
        """Ставит недельные отчёты за завершившиеся понедельник–пятницу."""

        target_day = end or date.today()
        friday = target_day - timedelta(days=(target_day.weekday() - 4) % 7)
        monday = friday - timedelta(days=4)
        managers = await self._repository.managers_with_completed_reports(
            "daily",
            monday,
            friday,
        )

        for manager_id in managers:
            await self._worker.enqueue(
                "weekly",
                f"{manager_id}:{monday}:{friday}",
                manager_id,
                {
                    "period_start": str(monday),
                    "period_end": str(friday),
                },
            )
