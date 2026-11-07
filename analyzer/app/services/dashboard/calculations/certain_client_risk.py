from collections import defaultdict
from datetime import date, timedelta

from app.services.dashboard.calculations.dashboard_history import RISK_LEVELS, rows_between


def calculate_certain_client_risks(history, report_date: date, days: int) -> dict[str, dict]:
    start = report_date - timedelta(days=days - 1)
    grouped = defaultdict(lambda: defaultdict(list))
    for daily in rows_between(history, start, report_date):
        for risk in daily.get("risks", []):
            grouped[risk["clientEpk"]][risk["metricCode"]].append(risk)

    result = {}
    for client_epk, by_code in grouped.items():
        risks = []
        latest_client_occurrence = None
        for code, occurrences in by_code.items():
            latest = max(occurrences, key=lambda item: item["occurredAt"])
            if (
                latest_client_occurrence is None
                or latest["occurredAt"] > latest_client_occurrence["occurredAt"]
            ):
                latest_client_occurrence = latest
            risks.append({
                "metricCode": code,
                "title": latest["title"],
                "level": latest["severity"],
                "quote": latest.get("quote") or "",
                "count": _unique_calls_count(occurrences),
                "recommendation": latest["recommendation"],
            })
        risks.sort(key=lambda item: (-RISK_LEVELS.get(item["level"], 0), item["metricCode"]))
        client_fio = ""
        if latest_client_occurrence is not None:
            client_fio = latest_client_occurrence.get("clientFio") or ""
        client_level = "low"
        client_level_value = 0
        for risk in risks:
            risk_level_value = RISK_LEVELS.get(risk["level"], 0)
            if risk_level_value > client_level_value:
                client_level = risk["level"]
                client_level_value = risk_level_value
        result[client_epk] = {
            "clientEpk": client_epk,
            "clientFio": client_fio,
            "level": client_level,
            "risks": risks,
        }
    return result


def _unique_calls_count(occurrences: list[dict]) -> int:
    call_ids = set()
    for item in occurrences:
        call_ids.add(item["callId"])
    return len(call_ids)
