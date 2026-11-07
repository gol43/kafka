from datetime import UTC, date, datetime, timedelta
import logging

from app.config import Settings
from app.database.repositories.dashboard_repository import DashboardRepository
from app.database.repositories.dialog_report_repository import DialogReportRepository
from app.schemas.managers import ManagerProfile
from app.services.dashboard.calculations.certain_client_risk import (
    calculate_certain_client_risks,
)
from app.services.dashboard.calculations.certain_improvement_metric import (
    calculate_certain_improvement_metrics,
)
from app.services.dashboard.calculations.dashboard_history import (
    build_daily_history,
    build_completed_week,
    build_metric_statistics,
    chunks,
)
from app.services.dashboard.calculations.improvements import calculate_improvements
from app.services.dashboard.calculations.q_score import (
    calculate_q_score,
    month_score_state,
    quarter_score_state,
    team_medians,
)
from app.services.dashboard.calculations.risks import calculate_risks
from app.services.dashboard.calculations.strengths import calculate_strengths

logger = logging.getLogger(__name__)


class DashboardBuilder:
    """Вызывает расчёты восьми блоков и сохраняет готовые ответы."""

    def __init__(
        self,
        settings: Settings,
        dashboards: DashboardRepository,
        reports: DialogReportRepository,
    ) -> None:
        self._settings = settings
        self._dashboards = dashboards
        self._reports = reports

    async def rebuild(self, report_date: date) -> None:
        now = datetime.now(UTC)
        profiles = []
        manager_roles = self._settings.static_manager_roles()
        for manager_id, role in sorted(manager_roles.items()):
            profiles.append(ManagerProfile(managerId=manager_id, role=role))
        current = {}
        logger.info(
            "Dashboard build started date=%s managers=%s",
            report_date,
            len(profiles),
        )

        for batch in chunks(profiles, self._settings.dashboard_manager_batch_size):
            rows = await self._build_aggregates(batch, report_date)
            await self._dashboards.save_aggregates(rows, now)
            for row in rows:
                current[row["manager_id"]] = {
                    "quarter": row["quarter_score_data"],
                }

        medians = team_medians(profiles, current, self._settings.empty_score_value)
        for batch in chunks(profiles, self._settings.dashboard_manager_batch_size):
            rows = await self._build_snapshots(batch, report_date, medians)
            await self._dashboards.save_snapshots(rows, now)

        await self._dashboards.compact_history(
            report_date,
            self._settings.risk_rolling_window_days,
            self._settings.metric_history_days,
        )
        logger.info("Dashboard build completed date=%s", report_date)

    async def _build_aggregates(self, profiles, report_date: date) -> list[dict]:
        manager_ids = self._manager_ids(profiles)
        reports = await self._reports.for_work_date_many(manager_ids, report_date)
        previous_aggregates = await self._dashboards.latest_aggregates_before(
            manager_ids,
            report_date,
        )
        week_history = {}
        if report_date.weekday() == 4:
            week_start = report_date - timedelta(days=4)
            week_history = await self._dashboards.aggregates_between(
                manager_ids,
                week_start,
                report_date - timedelta(days=1),
            )
        rows = []
        for profile in profiles:
            daily = build_daily_history(reports[profile.manager_id])
            previous = previous_aggregates.get(profile.manager_id)
            previous_quarter = previous.get("quarter") if previous else None
            previous_month = previous.get("month") if previous else None
            rows.append({
                "manager_id": profile.manager_id,
                "aggregate_date": report_date,
                "manager_role": profile.role,
                "dialogs_count": daily["dialogsCount"],
                "dialog_score_sum": daily["dialogScoreSum"],
                "dialog_score_count": daily["dialogScoreCount"],
                "daily_metrics": daily["metrics"],
                "daily_risks": daily["risks"],
                "weekly_metrics": build_completed_week(
                    week_history.get(profile.manager_id, []),
                    daily,
                    report_date,
                ),
                "quarter_score_data": quarter_score_state(
                    previous_quarter,
                    daily,
                    report_date,
                ),
                "month_score_data": month_score_state(
                    previous_month,
                    daily,
                    report_date,
                ),
            })
        return rows

    async def _build_snapshots(self, profiles, report_date: date, medians: dict) -> list[dict]:
        manager_ids = self._manager_ids(profiles)
        history_days = self._dashboard_history_days()
        history = await self._dashboards.aggregates_between(
            manager_ids,
            report_date - timedelta(days=history_days - 1),
            report_date,
        )
        previous_snapshots = await self._dashboards.latest_snapshots_before(
            manager_ids,
            report_date,
        )
        rows = []
        for profile in profiles:
            manager_history = history[profile.manager_id]
            statistics = build_metric_statistics(manager_history, report_date, self._settings)
            strengths = calculate_strengths(statistics, self._settings)
            improvements = calculate_improvements(statistics, self._settings)
            latest_aggregate = self._latest_history_payload(manager_history)
            previous_snapshot = previous_snapshots.get(profile.manager_id)
            certain_client_risks = calculate_certain_client_risks(
                manager_history,
                report_date,
                self._settings.risk_rolling_window_days,
            )
            certain_improvement_metrics = calculate_certain_improvement_metrics(
                improvements,
                manager_history,
                self._settings,
            )
            for improvement in improvements:
                improvement.pop("recommendation", None)
            rows.append({
                "manager_id": profile.manager_id,
                "report_date": report_date,
                "manager_role": profile.role,
                "source_date": report_date,
                "carried_forward": False,
                "q_score": calculate_q_score(
                    latest_aggregate["quarter"],
                    latest_aggregate["month"],
                    previous_snapshot,
                    report_date,
                    medians[profile.role],
                    self._settings.empty_score_value,
                ),
                "risks": calculate_risks(certain_client_risks),
                "certain_client_risks": certain_client_risks,
                "strengths": strengths,
                "improvements": improvements,
                "certain_improvement_metrics": certain_improvement_metrics,
            })
        return rows

    def _dashboard_history_days(self) -> int:
        improvement_days = self._settings.certain_improvement_periods_limit * 7
        return max(
            self._settings.metric_history_days,
            self._settings.risk_rolling_window_days,
            self._settings.strengths_sample_window_days,
            improvement_days,
        )

    @staticmethod
    def _manager_ids(profiles) -> list[str]:
        result = []
        for profile in profiles:
            result.append(profile.manager_id)
        return result

    @staticmethod
    def _latest_history_payload(history) -> dict | None:
        if not history:
            return None
        return history[-1][1]

