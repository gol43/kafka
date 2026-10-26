from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from app.config import Settings
from app.database.repositories.dashboard_repository import DashboardRepository

SEVERITY_ORDER = {
    "fraud": 5,
    "critical": 4,
    "significant": 3,
    "minor": 2,
    "info": 1,
}


class DashboardBuilder:
    """Один раз в день собирает готовые read-модели восьми блоков."""

    def __init__(self, settings: Settings, repository: DashboardRepository) -> None:
        self._settings = settings
        self._repository = repository

    async def rebuild(self, snapshot_date: date) -> None:
        managers = sorted(self._settings.analyzed_manager_ids)
        quarter_start = _quarter_start(snapshot_date)
        quarter_dialogs = {
            manager_id: await self._repository.completed_dialogs(
                manager_id,
                quarter_start,
                snapshot_date,
            )
            for manager_id in managers
        }
        manager_scores = [
            _average([item.q_score for item in dialogs if item.q_score is not None])
            for dialogs in quarter_dialogs.values()
        ]
        team_median = _round(
            median([item for item in manager_scores if item is not None])
            if any(item is not None for item in manager_scores)
            else self._settings.empty_score_value
        )

        for manager_id in managers:
            await self._build_manager(
                manager_id,
                snapshot_date,
                quarter_dialogs[manager_id],
                team_median,
            )

    async def _build_manager(
        self,
        manager_id: str,
        snapshot_date: date,
        quarter_dialogs: list,
        team_median: float,
    ) -> None:
        current_start = snapshot_date - timedelta(
            days=self._settings.metric_rolling_window_days - 1
        )
        previous_start = current_start - timedelta(days=1)
        previous_end = snapshot_date - timedelta(days=1)
        metric_rows = await self._repository.metric_results(
            manager_id,
            previous_start,
            snapshot_date,
        )
        recent_dialogs = await self._repository.completed_dialogs(
            manager_id,
            current_start,
            snapshot_date,
        )
        all_dialogs = await self._repository.completed_dialogs(
            manager_id,
            None,
            snapshot_date,
        )
        dialogs_by_call = {item.call_id: item for item in recent_dialogs}

        current = _metric_stats(
            [item for item in metric_rows if item.occurred_at.date() >= current_start]
        )
        previous = _metric_stats(
            [
                item
                for item in metric_rows
                if previous_start <= item.occurred_at.date() <= previous_end
            ]
        )
        metrics = _metric_cards(current, previous)
        strengths = sorted(
            (
                item
                for item in metrics
                if item["currentPercent"] >= self._settings.strength_min_percent
            ),
            key=lambda item: (
                -SEVERITY_ORDER[item["severity"]],
                -item["currentPercent"],
                -item["communicationsCount"],
                item["metricCode"],
            ),
        )[: self._settings.strengths_limit]
        improvements = sorted(
            (
                item
                for item in metrics
                if item["currentPercent"] < self._settings.strength_min_percent
            ),
            key=lambda item: (
                -SEVERITY_ORDER[item["severity"]],
                item["currentPercent"],
                -item["communicationsCount"],
                item["metricCode"],
            ),
        )[: self._settings.improvements_limit]

        risks, client_details = _client_risks(
            metric_rows=[
                item
                for item in metric_rows
                if item.occurred_at.date() >= current_start and item.score == 0
            ],
            dialogs_by_call=dialogs_by_call,
            limit=self._settings.risk_clients_limit,
        )
        metric_details = [
            _metric_detail(
                item,
                metric_rows,
                dialogs_by_call,
                snapshot_date,
                self._settings.metric_weekly_points_limit,
                self._settings.metric_failed_communications_limit,
            )
            for item in improvements
        ]

        personal_score = _average(
            [item.q_score for item in quarter_dialogs if item.q_score is not None]
        )
        low_count = sum((item.q_score or 0) <= 40 for item in quarter_dialogs)
        payload = {
            "managerId": manager_id,
            "snapshotDate": str(snapshot_date),
            "qScore": {
                "personal": _round(personal_score or self._settings.empty_score_value),
                "teamMedian": team_median,
                "communicationsCount": len(quarter_dialogs),
                "lowScoreShare": _round(
                    low_count / len(quarter_dialogs) * 100
                    if quarter_dialogs
                    else self._settings.empty_score_value
                ),
                "months": _monthly_scores(quarter_dialogs, snapshot_date),
            },
            "clientsAtRisk": risks,
            "strengths": strengths,
            "improvements": improvements,
            "communications": [
                {
                    "callId": item.call_id,
                    "type": "call",
                    "clientFio": item.client_fio,
                    "occurredAt": item.occurred_at.isoformat() if item.occurred_at else None,
                    "score": item.q_score,
                }
                for item in all_dialogs[: self._settings.latest_communications_limit]
            ],
        }
        await self._repository.save_dashboard(
            manager_id,
            snapshot_date,
            payload,
            client_details,
            metric_details,
        )


def _metric_stats(rows: list) -> dict[str, dict]:
    grouped: dict[str, dict] = {}
    for row in rows:
        item = grouped.setdefault(
            row.metric_code,
            {
                "title": row.metric_title,
                "severity": row.severity,
                "passed": 0,
                "count": 0,
            },
        )
        item["passed"] += row.score
        item["count"] += 1
    return grouped


def _metric_cards(current: dict, previous: dict) -> list[dict]:
    cards = []
    for code, item in current.items():
        current_percent = item["passed"] / item["count"] * 100
        previous_item = previous.get(code)
        previous_percent = (
            previous_item["passed"] / previous_item["count"] * 100
            if previous_item
            else 0
        )
        cards.append(
            {
                "metricCode": code,
                "title": item["title"],
                "severity": item["severity"],
                "currentPercent": _round(current_percent),
                "previousPercent": _round(previous_percent),
                "delta": _round(current_percent - previous_percent),
                "communicationsCount": item["count"],
            }
        )
    return cards


def _client_risks(metric_rows: list, dialogs_by_call: dict, limit: int):
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for row in metric_rows:
        grouped[(row.client_epk, row.metric_code)].append(row)

    details = []
    for (client_epk, metric_code), rows in grouped.items():
        latest = max(rows, key=lambda item: item.occurred_at)
        dialog = dialogs_by_call.get(latest.call_id)
        details.append(
            {
                "clientEpk": client_epk,
                "clientFio": dialog.client_fio if dialog else "",
                "metricCode": metric_code,
                "metricTitle": latest.metric_title,
                "severity": latest.severity,
                "violationsCount": len(rows),
                "latestCallId": latest.call_id,
                "latestOccurredAt": latest.occurred_at.isoformat(),
                "latestQuote": latest.quote,
                "recommendation": latest.recommendation,
            }
        )

    details.sort(
        key=lambda item: (
            -SEVERITY_ORDER[item["severity"]],
            -date.fromisoformat(item["latestOccurredAt"][:10]).toordinal(),
            -item["violationsCount"],
            item["metricCode"],
        )
    )
    selected_by_client = {}
    for item in details:
        selected_by_client.setdefault(item["clientEpk"], item)
    selected = list(selected_by_client.values())[:limit]
    return selected, details


def _metric_detail(card, rows, dialogs_by_call, snapshot_date, weeks_limit, calls_limit):
    metric_rows = [item for item in rows if item.metric_code == card["metricCode"]]
    last_sunday = snapshot_date - timedelta(days=(snapshot_date.weekday() + 1) % 7)
    weekly = []
    for offset in reversed(range(weeks_limit)):
        end = last_sunday - timedelta(days=offset * 7)
        start = end - timedelta(days=6)
        week_rows = [item for item in metric_rows if start <= item.occurred_at.date() <= end]
        weekly.append(
            {
                "from": str(start),
                "to": str(end),
                "percent": _round(
                    sum(item.score for item in week_rows) / len(week_rows) * 100
                    if week_rows
                    else 0
                ),
            }
        )
    failed = sorted(
        (item for item in metric_rows if item.score == 0),
        key=lambda item: item.occurred_at,
        reverse=True,
    )[:calls_limit]
    return {
        **card,
        "recommendation": failed[0].recommendation if failed else "",
        "weekly": weekly,
        "communications": [
            {
                "callId": item.call_id,
                "type": "call",
                "clientFio": dialogs_by_call[item.call_id].client_fio
                if item.call_id in dialogs_by_call
                else "",
                "occurredAt": item.occurred_at.isoformat(),
                "quote": item.quote,
            }
            for item in failed
        ],
    }


def _monthly_scores(dialogs: list, snapshot_date: date) -> list[dict]:
    quarter_month = ((snapshot_date.month - 1) // 3) * 3 + 1
    result = []
    for month in range(quarter_month, quarter_month + 3):
        scores = [
            item.q_score
            for item in dialogs
            if item.occurred_at
            and item.occurred_at.month == month
            and item.q_score is not None
        ]
        result.append(
            {
                "year": snapshot_date.year,
                "month": month,
                "score": _round(_average(scores) or 0),
            }
        )
    return result


def _quarter_start(value: date) -> date:
    month = ((value.month - 1) // 3) * 3 + 1
    return date(value.year, month, 1)


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round(value: float) -> float:
    return round(float(value), 2)
