from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
import logging
from statistics import median

from app.config import Settings
from app.database.repositories.dashboard_repository import DashboardRepository
from app.database.repositories.dialog_report_repository import DialogReportRepository
from app.schemas.entities import DialogReportEntity

SEVERITY_ORDER = {
    "fraud": 8,
    "high": 7,
    "critical": 6,
    "medium": 5,
    "significant": 4,
    "low": 3,
    "minor": 2,
    "info": 1,
}

logger = logging.getLogger(__name__)


class DashboardBuilder:
    """Строит промежуточную математику и готовую витрину за один день."""

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
        # Источник менеджеров — реальные completed-отчёты, а не ENV-список.
        # Исторические менеджеры остаются в расчёте: при отпуске их последний
        # накопленный результат переносится в новый snapshot без новых звонков.
        managers = sorted(await self._reports.manager_ids_through(report_date))
        aggregate_data: dict[str, dict] = {}
        logger.info(
            "Dashboard build started date=%s managers=%s",
            report_date,
            len(managers),
        )

        # Сначала готовим математику всех менеджеров, чтобы затем посчитать медиану.
        for manager_id in managers:
            aggregate_data[manager_id] = await self._build_aggregate(
                manager_id,
                report_date,
                now,
            )

        personal_scores = [
            float(data["quarter"]["qScore"])
            for data in aggregate_data.values()
        ]
        team_median = _round(
            median(personal_scores)
            if personal_scores
            else self._settings.empty_score_value
        )

        for manager_id in managers:
            await self._build_snapshot(
                manager_id,
                report_date,
                aggregate_data[manager_id],
                team_median,
                now,
            )
            logger.info("Dashboard saved manager_id=%s date=%s", manager_id, report_date)

        await self._dashboards.cleanup_expired(now)
        logger.info("Dashboard build completed date=%s", report_date)

    async def _build_aggregate(
        self,
        manager_id: str,
        report_date: date,
        now: datetime,
    ) -> dict:
        reports = await self._reports.for_work_date(manager_id, report_date)
        daily = _daily_stats(reports)

        rolling_start = report_date - timedelta(
            days=self._settings.metric_rolling_window_days - 1
        )
        rolling_rows = await self._dashboards.aggregates_between(
            manager_id,
            rolling_start,
            report_date - timedelta(days=1),
        )
        rolling_metrics = _sum_daily_metrics(
            [data for _, data in rolling_rows] + [{"daily": daily}]
        )

        quarter_rows = await self._dashboards.aggregates_between(
            manager_id,
            _quarter_start(report_date),
            report_date - timedelta(days=1),
        )
        quarter = _period_score(
            [data for _, data in quarter_rows] + [{"daily": daily}]
        )

        week = {"completed": False}
        if report_date.weekday() == 4:
            week_start = report_date - timedelta(days=4)
            week_rows = await self._dashboards.aggregates_between(
                manager_id,
                week_start,
                report_date - timedelta(days=1),
            )
            week = {
                "completed": True,
                "periodStart": str(week_start),
                "periodEnd": str(report_date),
                "metrics": _sum_daily_metrics(
                    [data for _, data in week_rows] + [{"daily": daily}]
                ),
            }

        month_start = report_date.replace(day=1)
        month_rows = await self._dashboards.aggregates_between(
            manager_id,
            month_start,
            report_date - timedelta(days=1),
        )
        month_score = _period_score(
            [data for _, data in month_rows] + [{"daily": daily}]
        )
        month = {
            "completed": _is_last_workday_of_month(report_date),
            "month": report_date.month,
            "year": report_date.year,
            "periodStart": str(month_start),
            "periodEnd": str(report_date),
            "qScore": month_score["qScore"],
            "communicationsCount": month_score["dialogScoreCount"],
        }

        data = {
            "daily": daily,
            "rolling30": {"metrics": rolling_metrics},
            "quarter": quarter,
            "week": week,
            "month": month,
        }
        await self._dashboards.save_aggregate(manager_id, report_date, data, now)
        return data

    async def _build_snapshot(
        self,
        manager_id: str,
        report_date: date,
        aggregate: dict,
        team_median: float,
        now: datetime,
    ) -> None:
        history_start = report_date - timedelta(days=self._settings.data_ttl_days)
        history = await self._dashboards.aggregates_between(
            manager_id,
            history_start,
            report_date,
        )
        previous = history[-2][1] if len(history) > 1 else {}
        current_metrics = aggregate["rolling30"]["metrics"]
        previous_metrics = previous.get("rolling30", {}).get("metrics", {})
        metric_cards = _metric_cards(current_metrics, previous_metrics)

        strengths = sorted(
            (
                item
                for item in metric_cards
                if item["currentPercent"] >= self._settings.strength_min_percent
            ),
            key=lambda item: (
                -SEVERITY_ORDER.get(item["severity"], 0),
                -item["passedCount"],
                -item["currentPercent"],
                item["metricCode"],
            ),
        )[: self._settings.strengths_limit]
        improvements = sorted(
            (
                item
                for item in metric_cards
                if item["currentPercent"] < self._settings.strength_min_percent
            ),
            key=lambda item: (
                -SEVERITY_ORDER.get(item["severity"], 0),
                -item["failedCount"],
                item["currentPercent"],
                item["metricCode"],
            ),
        )[: self._settings.improvements_limit]

        risks, risk_details = _risk_blocks(
            history,
            report_date,
            self._settings.risk_rolling_window_days,
            self._settings.risk_clients_limit,
        )
        improvement_details = _improvement_details(
            improvements,
            history,
            self._settings.metric_weekly_points_limit,
            current_metrics,
        )
        communications = await self._reports.list_for_manager(
            manager_id=manager_id,
            report_date=report_date,
            limit=self._settings.latest_communications_limit,
        )
        q_score = _q_score_block(
            aggregate,
            history,
            report_date,
            team_median,
            self._settings.empty_score_value,
        )

        await self._dashboards.save_snapshot(
            manager_id=manager_id,
            report_date=report_date,
            q_score_block=q_score,
            client_risks_block=risks,
            client_risk_details=risk_details,
            strengths_block=strengths,
            improvements_block=improvements,
            improvement_details=improvement_details,
            communications_block=[_communication(item) for item in communications],
            source_call_ids=[item.call_id for item in communications],
            now=now,
        )


def _daily_stats(reports: list[DialogReportEntity]) -> dict:
    metrics: dict[str, dict] = {}
    risks: list[dict] = []
    for report in reports:
        for item in report.hygiene_results + report.deposit_results:
            if not item.get("included_in_analytics", False):
                continue
            metric = metrics.setdefault(
                item["code"],
                {
                    "title": item["title"],
                    "severity": item["severity"],
                    "recommendation": item["recommendation"],
                    "passed": 0,
                    "failed": 0,
                    "total": 0,
                    "violations": [],
                },
            )
            metric["passed"] += int(item["score"] == 1)
            metric["failed"] += int(item["score"] == 0)
            metric["total"] += 1
            if item["score"] == 0:
                metric["violations"].append(
                    {
                        "callId": report.call_id,
                        "type": "call",
                        "clientEpk": report.client_epk,
                        "occurredAt": report.occurred_at.isoformat(),
                        "quote": item.get("quote"),
                    }
                )

        for item in report.risk_results:
            if item["score"] != 0:
                continue
            risks.append(
                {
                    "clientEpk": report.client_epk,
                    "callId": report.call_id,
                    "metricCode": item["code"],
                    "title": item["title"],
                    "severity": item["severity"],
                    "quote": item.get("quote"),
                    "recommendation": item["recommendation"],
                    "occurredAt": report.occurred_at.isoformat(),
                }
            )

    return {
        "dialogsCount": len(reports),
        "dialogScoreSum": _round(sum(item.score for item in reports)),
        "dialogScoreCount": len(reports),
        "metrics": metrics,
        "risks": risks,
    }


def _sum_daily_metrics(rows: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in rows:
        for code, item in row.get("daily", {}).get("metrics", {}).items():
            metric = result.setdefault(
                code,
                {
                    "title": item["title"],
                    "severity": item["severity"],
                    "recommendation": item["recommendation"],
                    "passed": 0,
                    "failed": 0,
                    "total": 0,
                    "percent": 0.0,
                    "violations": [],
                },
            )
            metric["passed"] += item["passed"]
            metric["failed"] += item["failed"]
            metric["total"] += item["total"]
            metric["violations"].extend(item.get("violations", []))
    for item in result.values():
        item["percent"] = _round(
            item["passed"] / item["total"] * 100 if item["total"] else 0
        )
    return result


def _period_score(rows: list[dict]) -> dict:
    score_sum = sum(row.get("daily", {}).get("dialogScoreSum", 0) for row in rows)
    count = sum(row.get("daily", {}).get("dialogScoreCount", 0) for row in rows)
    return {
        "dialogScoreSum": _round(score_sum),
        "dialogScoreCount": count,
        "qScore": _round(score_sum / count if count else 0),
    }


def _metric_cards(current: dict, previous: dict) -> list[dict]:
    cards = []
    for code, item in current.items():
        previous_percent = previous.get(code, {}).get("percent", 0)
        cards.append(
            {
                "metricCode": code,
                "title": item["title"],
                "severity": item["severity"],
                "currentPercent": item["percent"],
                "previousPercent": previous_percent,
                "delta": _round(item["percent"] - previous_percent),
                "passedCount": item["passed"],
                "failedCount": item["failed"],
                "communicationsCount": item["total"],
                "recommendation": item["recommendation"],
            }
        )
    return cards


def _risk_blocks(history, report_date, days, limit):
    start = report_date - timedelta(days=days - 1)
    events = [
        event
        for day, data in history
        if day >= start
        for event in data.get("daily", {}).get("risks", [])
    ]
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in events:
        grouped[(event["clientEpk"], event["metricCode"])].append(event)

    candidates = []
    for (client_epk, metric_code), items in grouped.items():
        items.sort(key=lambda value: value["occurredAt"], reverse=True)
        latest = items[0]
        candidates.append(
            {
                "clientEpk": client_epk,
                "metricCode": metric_code,
                "title": latest["title"],
                "severity": latest["severity"],
                "violationsCount": len(items),
                "latestCallId": latest["callId"],
                "latestOccurredAt": latest["occurredAt"],
                "latestQuote": latest["quote"],
                "recommendation": latest["recommendation"],
                "communications": items,
            }
        )
    candidates.sort(
        key=lambda item: (
            -SEVERITY_ORDER.get(item["severity"], 0),
            -datetime.fromisoformat(item["latestOccurredAt"]).timestamp(),
            -item["violationsCount"],
            item["metricCode"],
        )
    )
    selected: dict[str, dict] = {}
    for item in candidates:
        selected.setdefault(item["clientEpk"], item)
    values = list(selected.values())[:limit]
    details = {item["clientEpk"]: item for item in values}
    cards = [{key: value for key, value in item.items() if key != "communications"} for item in values]
    return cards, details


def _improvement_details(improvements, history, weekly_limit, current_metrics):
    completed_weeks = [
        data["week"]
        for _, data in history
        if data.get("week", {}).get("completed")
    ]
    details = {}
    for card in improvements:
        code = card["metricCode"]
        weekly = []
        for week in completed_weeks[-weekly_limit:]:
            metric = week.get("metrics", {}).get(code)
            weekly.append(
                {
                    "from": week["periodStart"],
                    "to": week["periodEnd"],
                    "percent": metric["percent"] if metric else 0,
                }
            )
        details[code] = {
            **card,
            "recommendation": card["recommendation"],
            "weekly": weekly,
            "communications": sorted(
                current_metrics.get(code, {}).get("violations", []),
                key=lambda item: item["occurredAt"],
                reverse=True,
            ),
        }
    return details


def _q_score_block(aggregate, history, report_date, team_median, empty_score):
    quarter_start = _quarter_start(report_date)
    months = []
    for offset in range(3):
        month_number = quarter_start.month + offset
        candidates = [
            data["month"]
            for day, data in history
            if day.year == quarter_start.year
            and day.month == month_number
            and data.get("month")
        ]
        latest = candidates[-1] if candidates else None
        months.append(
            {
                "year": quarter_start.year,
                "month": month_number,
                "qScore": latest["qScore"] if latest else empty_score,
                "communicationsCount": (
                    latest["communicationsCount"] if latest else 0
                ),
            }
        )
    quarter = aggregate["quarter"]
    return {
        "personal": quarter.get("qScore", empty_score),
        "teamMedian": team_median,
        "communicationsCount": quarter.get("dialogScoreCount", 0),
        "months": months,
    }


def _communication(report: DialogReportEntity) -> dict:
    return {
        "callId": report.call_id,
        "type": "call",
        "clientEpk": report.client_epk,
        "occurredAt": report.occurred_at.isoformat(),
        "score": report.score,
    }


def _quarter_start(value: date) -> date:
    return date(value.year, ((value.month - 1) // 3) * 3 + 1, 1)


def _is_last_workday_of_month(value: date) -> bool:
    next_day = value + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day.month != value.month


def _round(value: float) -> float:
    return round(float(value), 2)
