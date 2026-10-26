import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import ClassVar

from app.agents.gigachat_provider.base import BaseGigaChatProvider
from app.agents.report_agent import ReportAgent
from app.config import Settings
from app.database.repositories.report_repository import ReportRepository
from app.schemas.entities import AggregateReportEntity, DialogEntity
from app.services.batching import build_recommendation_with_batches

logger = logging.getLogger(__name__)


class ReportOrchestrator:
    """Явная точка запуска daily, weekly, four-week и quarterly отчётов."""

    CHILD_REPORT_TYPES: ClassVar[dict[str, str]] = {
        "weekly": "daily",
        "four_week": "weekly",
        "quarterly": "four_week",
    }
    REQUIRED_SOURCE_COUNTS: ClassVar[dict[str, int]] = {
        "four_week": 4,
        "quarterly": 3,
    }

    def __init__(
        self,
        settings: Settings,
        repository: ReportRepository,
        provider: BaseGigaChatProvider,
        agent: ReportAgent,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._provider = provider
        self._agent = agent

    async def build_daily(
        self,
        manager_id: str,
        report_date: date,
    ) -> AggregateReportEntity:
        """Строит дневной отчёт из завершённых анализов диалогов."""

        return await self._build("daily", manager_id, report_date, report_date)

    async def build_weekly(
        self,
        manager_id: str,
        period_start: date,
        period_end: date,
    ) -> AggregateReportEntity:
        """Строит недельный отчёт из дневных отчётов."""

        return await self._build("weekly", manager_id, period_start, period_end)

    async def build_four_week(
        self,
        manager_id: str,
        period_start: date,
        period_end: date,
    ) -> AggregateReportEntity:
        """Строит four-week отчёт строго из четырёх недельных отчётов."""

        return await self._build("four_week", manager_id, period_start, period_end)

    async def build_quarterly(
        self,
        manager_id: str,
        period_start: date,
        period_end: date,
    ) -> AggregateReportEntity:
        """Строит квартальный отчёт из трёх four-week отчётов."""

        return await self._build("quarterly", manager_id, period_start, period_end)

    async def build(
        self,
        report_type: str,
        manager_id: str,
        period_start: date,
        period_end: date,
    ) -> AggregateReportEntity:
        """Диспетчеризует техническое задание в явно названный сценарий."""

        builders = {
            "daily": self.build_daily,
            "weekly": self.build_weekly,
            "four_week": self.build_four_week,
            "quarterly": self.build_quarterly,
        }
        if report_type == "daily":
            return await self.build_daily(manager_id, period_start)
        return await builders[report_type](manager_id, period_start, period_end)

    async def _build(
        self,
        report_type: str,
        manager_id: str,
        start: date,
        end: date,
    ) -> AggregateReportEntity:
        source_data = await self._load_sources(report_type, manager_id, start, end)
        logger.info(
            "Report sources loaded type=%s manager=%s count=%s",
            report_type,
            manager_id,
            len(source_data.source_ids),
        )
        required_count = self.REQUIRED_SOURCE_COUNTS.get(report_type)
        if required_count is not None and len(source_data.source_ids) != required_count:
            raise ValueError("Недостаточно отчётов предыдущего уровня")
        if not source_data.items or source_data.communications_count == 0:
            raise ValueError("Нет завершённых источников для отчёта")

        available_tokens = (
            self._settings.gigachat_max_input_tokens
            - self._settings.gigachat_prompt_reserve_tokens
            - self._settings.gigachat_output_reserve_tokens
        )
        if available_tokens <= 0:
            raise ValueError("Некорректный лимит входных токенов")

        logger.info("Report agent started type=%s manager=%s", report_type, manager_id)
        summary = await build_recommendation_with_batches(
            provider=self._provider,
            agent=self._agent,
            items=source_data.items,
            report_type=report_type,
            max_tokens=available_tokens,
            max_items=self._settings.aggregation_max_batch_items,
        )
        report = await self._repository.save_completed(
            report_type=report_type,
            manager_id=manager_id,
            start=start,
            end=end,
            report_version=self._settings.report_version,
            score_sum=source_data.score_sum,
            communications_count=source_data.communications_count,
            summary=summary,
            details={
                "source_count": len(source_data.source_ids),
                "criteria": source_data.criteria,
            },
            source_ids=source_data.source_ids,
        )
        logger.info("Report result saved type=%s manager=%s", report_type, manager_id)
        return report

    async def _load_sources(
        self,
        report_type: str,
        manager_id: str,
        start: date,
        end: date,
    ) -> "ReportSourceData":
        if report_type == "daily":
            dialogs = await self._repository.daily_sources(manager_id, start)
            return self._dialog_sources(dialogs)

        child_type = self.CHILD_REPORT_TYPES[report_type]
        reports = await self._repository.period_sources(
            manager_id,
            child_type,
            start,
            end,
        )
        return self._report_sources(reports)

    @staticmethod
    def _dialog_sources(dialogs: list[DialogEntity]) -> "ReportSourceData":
        items = [
            json.dumps(
                {
                    "call_id": dialog.call_id,
                    "q_score": dialog.q_score,
                    "criteria": ReportOrchestrator._dialog_criteria(dialog),
                },
                ensure_ascii=False,
            )
            for dialog in dialogs
        ]
        criteria = ReportOrchestrator._aggregate_dialog_criteria(dialogs)
        return ReportSourceData(
            items=items,
            score_sum=sum(dialog.q_score or 0 for dialog in dialogs),
            communications_count=len(dialogs),
            source_ids=[dialog.call_id for dialog in dialogs],
            criteria=criteria,
        )

    @staticmethod
    def _report_sources(
        reports: list[AggregateReportEntity],
    ) -> "ReportSourceData":
        items = [
            json.dumps(
                {
                    "period": ReportOrchestrator._report_period(report),
                    "q_score": report.q_score,
                    "summary": report.summary,
                    "criteria": report.details.get("criteria", {}),
                },
                ensure_ascii=False,
            )
            for report in reports
        ]
        return ReportSourceData(
            items=items,
            score_sum=sum(report.score_sum or 0 for report in reports),
            communications_count=sum(report.communications_count for report in reports),
            source_ids=[str(report.id) for report in reports],
            criteria=ReportOrchestrator._merge_period_criteria(reports),
        )

    @staticmethod
    def _report_period(
        report: AggregateReportEntity,
    ) -> list[str]:
        return [str(report.period_start), str(report.period_end)]

    @staticmethod
    def _aggregate_dialog_criteria(
        dialogs: list[DialogEntity],
    ) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for dialog in dialogs:
            for criterion in ReportOrchestrator._dialog_criteria(dialog):
                stats = result.setdefault(
                    criterion["code"],
                    {
                        "passed_count": 0,
                        "violation_count": 0,
                        "communications_count": 0,
                    },
                )
                stats["communications_count"] += 1
                field = "passed_count" if criterion["score"] == 1 else "violation_count"
                stats[field] += 1
        return result

    @staticmethod
    def _dialog_criteria(dialog: DialogEntity) -> list[dict]:
        """Достаёт критерии из единственного объекта результата анализа."""

        return dialog.analysis_results.get("prompt", {}).get("criteria", [])

    @staticmethod
    def _merge_period_criteria(
        reports: list[AggregateReportEntity],
    ) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for report in reports:
            for code, source in report.details.get("criteria", {}).items():
                target = result.setdefault(
                    code,
                    {
                        "passed_count": 0,
                        "violation_count": 0,
                        "communications_count": 0,
                    },
                )
                for field in target:
                    target[field] += int(source.get(field, 0))
        return result


@dataclass(slots=True)
class ReportSourceData:
    """Данные, которые живут в памяти только во время сборки одного отчёта."""

    items: list[str]
    score_sum: float
    communications_count: int
    source_ids: list[str]
    criteria: dict[str, dict[str, int]]
