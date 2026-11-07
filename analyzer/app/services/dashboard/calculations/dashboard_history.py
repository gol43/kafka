from datetime import date, timedelta
import math

from app.schemas.entities import DashboardDialogEntity


SEVERITY_LEVELS = {"critical": 3, "significant": 2, "minor": 1, "info": 0}
RISK_LEVELS = {"high": 3, "medium": 2, "low": 1}


def build_daily_history(reports: list[DashboardDialogEntity]) -> dict:
    metrics: dict[str, dict] = {}
    risks: list[dict] = []
    for report in reports:
        for item in report.hygiene_results + report.deposit_results:
            if not item.get("included_in_analytics", False):
                continue
            metric = metrics.setdefault(item["code"], {
                "title_positive": item["title_positive"],
                "title_negative": item["title_negative"],
                "severity": item["severity"],
                "recommendation": item["recommendation"],
                "passed": 0, "failed": 0, "total": 0, "violations": [],
            })
            metric["passed"] += int(item["score"] == 1)
            metric["failed"] += int(item["score"] == 0)
            metric["total"] += 1
            if item["score"] == 0:
                metric["violations"].append({
                    "callId": report.call_id,
                    "type": "call",
                    "clientEpk": report.client_epk,
                    "occurredAt": report.occurred_at.isoformat(),
                })
        for item in report.risk_results:
            if item["score"] == 0:
                risks.append({
                    "clientEpk": report.client_epk,
                    "clientFio": report.client_fio,
                    "callId": report.call_id,
                    "metricCode": item["code"],
                    "title": item["title_negative"],
                    "severity": item["severity"],
                    "quote": item.get("quote") or "",
                    "recommendation": item["recommendation"],
                    "occurredAt": report.occurred_at.isoformat(),
                })
    dialog_score_sum = 0
    for report in reports:
        dialog_score_sum += report.score

    return {
        "dialogsCount": len(reports),
        "dialogScoreSum": dialog_score_sum,
        "dialogScoreCount": len(reports),
        "metrics": metrics,
        "risks": risks,
    }


def rows_between(history, start: date, end: date) -> list[dict]:
    result = []
    for day, payload in history:
        if start <= day <= end:
            result.append(payload["daily"])
    return result


def sum_metrics(rows: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for daily in rows:
        for code, item in daily.get("metrics", {}).items():
            metric = result.setdefault(code, {
                "title_positive": item["title_positive"],
                "title_negative": item["title_negative"],
                "severity": item["severity"],
                "recommendation": item["recommendation"],
                "passed": 0, "failed": 0, "total": 0, "violations": [],
            })
            for field in ("passed", "failed", "total"):
                metric[field] += item[field]
            metric["violations"].extend(item.get("violations", []))
    return result


def build_metric_statistics(history, report_date: date, settings) -> list[dict]:
    """Готовит два непересекающихся окна для Strengths и Improvements."""
    size = settings.strengths_improvements_period_days
    current_start = report_date - timedelta(days=size - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=size - 1)
    sample_start = report_date - timedelta(days=settings.strengths_sample_window_days - 1)
    current = sum_metrics(rows_between(history, current_start, report_date))
    previous = sum_metrics(rows_between(history, previous_start, previous_end))
    sample = sum_metrics(rows_between(history, sample_start, report_date))
    result = []
    for code, metric in current.items():
        if code in settings.ui_hidden_metric_codes:
            continue
        total = metric["total"]
        if not total:
            continue
        old = previous.get(code, {"passed": 0, "failed": 0, "total": 0})
        positive = metric["passed"] / total * 100
        negative = metric["failed"] / total * 100
        old_positive = old["passed"] / old["total"] * 100 if old["total"] else 0
        old_negative = old["failed"] / old["total"] * 100 if old["total"] else 0
        severity = SEVERITY_LEVELS.get(metric["severity"], 0) / 3 * 0.6
        result.append({
            "metricCode": code,
            "title_positive": metric["title_positive"],
            "title_negative": metric["title_negative"],
            "recommendation": metric["recommendation"],
            "positive1": int(positive), "positive2": int(old_positive),
            "negative1": int(negative), "negative2": int(old_negative),
            "sampleTotal": sample.get(code, {}).get("total", 0),
            "strengthRating": severity + math.log1p(metric["passed"]) / math.log1p(total) * 0.4,
            "improvementRating": severity + math.log1p(metric["failed"]) / math.log1p(total) * 0.4,
        })
    return result


def build_completed_week(
    history,
    daily: dict,
    report_date: date,
) -> dict | None:
    if report_date.weekday() != 4:
        return None

    period_start = report_date - timedelta(days=4)
    period_end = period_start + timedelta(days=6)
    rows = rows_between(history, period_start, report_date - timedelta(days=1))
    rows.append(daily)
    metrics = sum_metrics(rows)
    percentages = {}
    for code, metric in metrics.items():
        total = metric["total"]
        percent = 0
        if total:
            percent = int(metric["failed"] / total * 100)
        percentages[code] = percent

    return {
        "completed": True,
        "periodStart": str(period_start),
        "periodEnd": str(period_end),
        "metrics": percentages,
    }


def chunks(values, size):
    for index in range(0, len(values), size):
        yield values[index:index + size]


