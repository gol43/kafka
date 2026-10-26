from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

from app.config import Settings
from app.database.repositories.report_repository import ReportRepository
from app.schemas.entities import AggregateReportEntity


@dataclass(frozen=True, slots=True)
class ReportPromotion:
    """Параметры задания следующего уровня отчёта."""

    report_type: str
    manager_id: str
    period_start: date
    period_end: date


class ReportPromotionService:
    """Повышает готовый отчёт без отдельного опроса по расписанию."""

    def __init__(self, settings: Settings, repository: ReportRepository) -> None:
        self._settings = settings
        self._repository = repository

    async def after_completed(
        self,
        report_type: str,
        manager_id: str,
    ) -> ReportPromotion | None:
        """Возвращает следующее задание, когда накоплены все источники."""

        rules = {
            "weekly": (
                "four_week",
                4,
                self._settings.four_week_report_enabled,
            ),
            "four_week": (
                "quarterly",
                3,
                self._settings.quarterly_report_enabled,
            ),
        }
        rule = rules.get(report_type)
        if rule is None:
            return None

        target_type, required, enabled = rule
        if not enabled:
            return None

        reports = await self._repository.unconsumed_reports(
            manager_id,
            report_type,
        )
        sources = self._first_consecutive(reports, required)
        if not sources:
            return None

        return ReportPromotion(
            report_type=target_type,
            manager_id=manager_id,
            period_start=sources[0].period_start,
            period_end=sources[-1].period_end,
        )

    @staticmethod
    def _first_consecutive(
        reports: list[AggregateReportEntity],
        required: int,
    ) -> list[AggregateReportEntity]:
        """Находит первую полную последовательность периодов."""

        if len(reports) < required:
            return []

        for start_index in range(len(reports) - required + 1):
            candidate = reports[start_index : start_index + required]
            if all(
                left.period_end + timedelta(days=3) == right.period_start
                for left, right in pairwise(candidate)
            ):
                return candidate

        return []
