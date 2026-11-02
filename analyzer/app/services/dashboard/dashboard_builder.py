from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
import logging
from statistics import median

from app.config import Settings
from app.database.repositories.dashboard_repository import DashboardRepository
from app.database.repositories.dialog_report_repository import DialogReportRepository
from app.schemas.entities import DialogReportEntity
from app.schemas.managers import ManagerProfile

logger = logging.getLogger(__name__)

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


class DashboardBuilder:
    """Пакетно строит дневную математику и готовую витрину."""

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
        profiles = [
            ManagerProfile(managerId=manager_id, role=role)
            for manager_id, role in sorted(
                self._settings.static_manager_roles().items()
            )
        ]
        current: dict[str, dict] = {}

        logger.info(
            "Dashboard build started date=%s managers=%s",
            report_date,
            len(profiles),
        )

        for batch in _chunks(profiles, self._settings.dashboard_manager_batch_size):
            rows = await self._build_aggregate_batch(batch, report_date)
            await self._dashboards.save_aggregates(rows, now)
            current.update({row["manager_id"]: _row_payload(row) for row in rows})

        medians = _team_medians(profiles, current, self._settings.empty_score_value)

        for batch in _chunks(profiles, self._settings.dashboard_manager_batch_size):
            snapshots = await self._build_snapshot_batch(
                batch,
                report_date,
                current,
                medians,
            )
            await self._dashboards.save_snapshots(snapshots, now)

        await self._dashboards.compact_history(
            report_date,
            self._settings.risk_rolling_window_days,
            self._settings.metric_rolling_window_days,
            self._settings.metric_weekly_points_limit,
        )
        await self._dashboards.cleanup_expired(
            now,
            self._settings.dashboard_cleanup_batch_size,
        )
        logger.info("Dashboard build completed date=%s", report_date)

    async def _build_aggregate_batch(
        self,
        profiles: list[ManagerProfile],
        report_date: date,
    ) -> list[dict]:
        manager_ids = [profile.manager_id for profile in profiles]
        reports = await self._reports.for_work_date_many(manager_ids, report_date)
        history = await self._dashboards.aggregates_between(
            manager_ids,
            report_date - timedelta(days=self._settings.data_ttl_days),
            report_date - timedelta(days=1),
        )
        rows = []
        for profile in profiles:
            daily = _daily_stats(reports[profile.manager_id])
            manager_history = history[profile.manager_id]
            rolling = _sum_daily_metrics(
                _daily_rows(
                    manager_history,
                    report_date
                    - timedelta(
                        days=self._settings.metric_rolling_window_days - 1
                    ),
                )
                + [daily]
            )
            quarter = _period_score(
                _daily_rows(manager_history, _quarter_start(report_date)) + [daily]
            )
            month = _month_score(manager_history, daily, report_date)
            week = _week_score(manager_history, daily, report_date)
            rows.append(
                {
                    "manager_id": profile.manager_id,
                    "aggregate_date": report_date,
                    "manager_role": profile.role,
                    "dialogs_count": daily["dialogsCount"],
                    "dialog_score_sum": daily["dialogScoreSum"],
                    "dialog_score_count": daily["dialogScoreCount"],
                    "daily_metrics": daily["metrics"],
                    "daily_risks": daily["risks"],
                    "rolling_30_metrics": rolling,
                    "weekly_metrics": week,
                    "quarter_score_data": quarter,
                    "month_score_data": month,
                }
            )
        return rows

    async def _build_snapshot_batch(
        self,
        profiles: list[ManagerProfile],
        report_date: date,
        current: dict[str, dict],
        medians: dict[str, float],
    ) -> list[dict]:
        manager_ids = [profile.manager_id for profile in profiles]
        history = await self._dashboards.aggregates_between(
            manager_ids,
            report_date - timedelta(days=self._settings.data_ttl_days),
            report_date,
        )
        previous = await self._dashboards.latest_snapshots_before(
            manager_ids,
            report_date,
        )
        communications = await self._reports.latest_for_managers(
            manager_ids,
            report_date,
            self._settings.latest_communications_limit,
        )

        rows = []
        for profile in profiles:
            aggregate = current[profile.manager_id]
            team_median = medians[profile.role]
            previous_snapshot = previous.get(profile.manager_id)
            manager_history = history[profile.manager_id]

            if aggregate["daily"]["dialogsCount"] == 0 and previous_snapshot:
                rows.append(
                    _carry_snapshot(
                        previous_snapshot,
                        profile,
                        report_date,
                        _q_score_block(
                            aggregate,
                            manager_history,
                            report_date,
                            team_median,
                            self._settings.empty_score_value,
                        ),
                    )
                )
                continue

            previous_metrics = _previous_metrics(manager_history, report_date)
            cards = _metric_cards(
                aggregate["rolling30"]["metrics"],
                previous_metrics,
            )
            strengths, improvements = _rank_metric_cards(cards, self._settings)
            risks, risk_details = _risk_blocks(
                manager_history,
                report_date,
                self._settings.risk_rolling_window_days,
            )
            improvement_details = _improvement_details(
                improvements,
                manager_history,
                self._settings.metric_weekly_points_limit,
                aggregate["rolling30"]["metrics"],
                self._settings.metric_failed_communications_limit,
            )
            recent = communications[profile.manager_id]
            rows.append(
                {
                    "manager_id": profile.manager_id,
                    "report_date": report_date,
                    "manager_role": profile.role,
                    "source_date": report_date,
                    "carried_forward": False,
                    "q_score_block": _q_score_block(
                        aggregate,
                        manager_history,
                        report_date,
                        team_median,
                        self._settings.empty_score_value,
                    ),
                    "client_risks_block": risks,
                    "client_risk_details": risk_details,
                    "strengths_block": strengths,
                    "improvements_block": improvements,
                    "improvement_details": improvement_details,
                    "communications_block": [_communication(item) for item in recent],
                    "source_call_ids": [item.call_id for item in recent],
                }
            )
        return rows


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
    for daily in rows:
        for code, item in daily.get("metrics", {}).items():
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
    for metric in result.values():
        metric["percent"] = _round(
            metric["passed"] / metric["total"] * 100 if metric["total"] else 0
        )
    return result


def _period_score(rows: list[dict]) -> dict:
    score_sum = sum(row.get("dialogScoreSum", 0) for row in rows)
    count = sum(row.get("dialogScoreCount", 0) for row in rows)
    return {
        "dialogScoreSum": _round(score_sum),
        "dialogScoreCount": count,
        "qScore": _round(score_sum / count if count else 0),
    }


def _month_score(history, daily, report_date):
    score = _period_score(
        _daily_rows(history, report_date.replace(day=1)) + [daily]
    )
    return {
        "month": report_date.month,
        "year": report_date.year,
        "periodEnd": str(report_date),
        "qScore": score["qScore"],
        "communicationsCount": score["dialogScoreCount"],
    }


def _week_score(history, daily, report_date):
    if report_date.weekday() != 4:
        return None
    start = report_date - timedelta(days=4)
    return {
        "completed": True,
        "periodStart": str(start),
        "periodEnd": str(report_date + timedelta(days=2)),
        "metrics": _sum_daily_metrics(_daily_rows(history, start) + [daily]),
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
                "delta": _round(previous_percent - item["percent"]),
                "passedCount": item["passed"],
                "failedCount": item["failed"],
                "communicationsCount": item["total"],
                "recommendation": item["recommendation"],
            }
        )
    return cards


def _rank_metric_cards(cards, settings):
    strengths = sorted(
        (item for item in cards if item["currentPercent"] >= settings.strength_min_percent),
        key=lambda item: (-item["passedCount"], -item["currentPercent"], item["metricCode"]),
    )[: settings.strengths_limit]
    improvements = sorted(
        (item for item in cards if item["currentPercent"] < settings.strength_min_percent),
        key=lambda item: (
            -SEVERITY_ORDER.get(item["severity"], 0),
            -item["failedCount"],
            item["currentPercent"],
            item["metricCode"],
        ),
    )[: settings.improvements_limit]
    return strengths, improvements


def _risk_blocks(history, report_date, days):
    start = report_date - timedelta(days=days - 1)
    events = [
        event
        for day, data in history
        if day >= start
        for event in data.get("daily", {}).get("risks", [])
    ]
    clients: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        clients[event["clientEpk"]].append(event)

    cards = []
    details = {}
    for client_epk, client_events in clients.items():
        risk_groups: dict[str, list[dict]] = defaultdict(list)
        for event in client_events:
            risk_groups[event["metricCode"]].append(event)
        risk_items = []
        all_calls = set()
        for code, risk_events in risk_groups.items():
            risk_events.sort(key=lambda item: item["occurredAt"], reverse=True)
            latest = risk_events[0]
            call_ids = {item["callId"] for item in risk_events}
            all_calls.update(call_ids)
            risk_items.append(
                {
                    "clientEpk": client_epk,
                    "metricCode": code,
                    "title": latest["title"],
                    "severity": latest["severity"],
                    "latestQuote": latest.get("quote"),
                    "latestCallId": latest["callId"],
                    "latestOccurredAt": latest["occurredAt"],
                    "communicationsCount": len(call_ids),
                    "recommendation": latest["recommendation"],
                }
            )
        severities = {item["severity"] for item in risk_items}
        if "high" in severities:
            level = "high"
        elif "medium" in severities:
            level = "medium"
        else:
            level = "low"
        latest_at = max(event["occurredAt"] for event in client_events)
        cards.append(
            {
                "clientEpk": client_epk,
                "level": level,
                "risksCount": len(risk_items),
                "communicationsCount": len(all_calls),
                "latestOccurredAt": latest_at,
                "riskTags": [item["title"] for item in risk_items],
            }
        )
        details[client_epk] = {
            "clientEpk": client_epk,
            "level": level,
            "risks": risk_items,
        }
    cards.sort(key=lambda item: {"high": 0, "medium": 1, "low": 2}[item["level"]])
    return cards, details


def _improvement_details(
    improvements,
    history,
    weekly_limit,
    current_metrics,
    communications_limit,
):
    weeks = [data["week"] for _, data in history if data.get("week", {}).get("completed")]
    details = {}
    for card in improvements:
        code = card["metricCode"]
        weekly = []
        for week in weeks[-weekly_limit:]:
            metric = week.get("metrics", {}).get(code)
            weekly.append(
                {
                    "from": week["periodStart"],
                    "to": week["periodEnd"],
                    "percent": metric["percent"] if metric else 0,
                }
            )
        violations = sorted(
            current_metrics.get(code, {}).get("violations", []),
            key=lambda item: item["occurredAt"],
            reverse=True,
        )
        details[code] = {
            **card,
            "weekly": weekly,
            "communications": violations[:communications_limit],
        }
    return details


def _q_score_block(aggregate, history, report_date, team_median, empty_score):
    months = []
    cursor = report_date.replace(day=1)
    month_keys = []
    for _ in range(5):
        month_keys.append((cursor.year, cursor.month))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    for year, month in reversed(month_keys):
        candidates = [
            data["month"]
            for day, data in history
            if day.year == year and day.month == month and data.get("month")
        ]
        latest = candidates[-1] if candidates else None
        months.append(
            {
                "year": year,
                "month": month,
                "qScore": latest["qScore"] if latest else empty_score,
                "communicationsCount": latest["communicationsCount"] if latest else 0,
            }
        )
    quarter = aggregate["quarter"]
    return {
        "personal": quarter.get("qScore", empty_score),
        "teamMedian": team_median,
        "communicationsCount": quarter.get("dialogScoreCount", 0),
        "months": months,
    }


def _carry_snapshot(previous, profile, report_date, q_score):
    return {
        "manager_id": profile.manager_id,
        "report_date": report_date,
        "manager_role": profile.role,
        "source_date": previous.source_date,
        "carried_forward": True,
        "q_score_block": q_score,
        "client_risks_block": previous.client_risks_block,
        "client_risk_details": previous.client_risk_details,
        "strengths_block": previous.strengths_block,
        "improvements_block": previous.improvements_block,
        "improvement_details": previous.improvement_details,
        "communications_block": previous.communications_block,
        "source_call_ids": previous.source_call_ids,
    }


def _team_medians(profiles, current, empty_score):
    scores: dict[str, list[float]] = defaultdict(list)
    for profile in profiles:
        scores[profile.role].append(float(current[profile.manager_id]["quarter"]["qScore"]))
    return {
        role: _round(median(values) if values else empty_score)
        for role, values in scores.items()
    }


def _row_payload(row):
    return {
        "managerRole": row["manager_role"],
        "daily": {
            "dialogsCount": row["dialogs_count"],
            "dialogScoreSum": row["dialog_score_sum"],
            "dialogScoreCount": row["dialog_score_count"],
            "metrics": row["daily_metrics"],
            "risks": row["daily_risks"],
        },
        "rolling30": {"metrics": row["rolling_30_metrics"]},
        "week": row["weekly_metrics"] or {"completed": False},
        "quarter": row["quarter_score_data"],
        "month": row["month_score_data"],
    }


def _daily_rows(history, start):
    return [data["daily"] for day, data in history if day >= start]


def _previous_metrics(history, report_date):
    candidates = [data["rolling30"]["metrics"] for day, data in history if day < report_date]
    return candidates[-1] if candidates else {}


def _communication(report):
    return {
        "callId": report.call_id,
        "type": "call",
        "clientEpk": report.client_epk,
        "occurredAt": report.occurred_at.isoformat(),
        "score": report.score,
    }


def _quarter_start(value):
    return date(value.year, ((value.month - 1) // 3) * 3 + 1, 1)


def _chunks(values, size):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _round(value):
    return round(float(value), 2)
