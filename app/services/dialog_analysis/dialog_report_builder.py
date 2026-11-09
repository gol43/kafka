import hashlib

from app.schemas.entities import DialogEntity

SEVERITY_ORDER = {
    "high": 7,
    "critical": 6,
    "medium": 5,
    "significant": 4,
    "low": 3,
    "minor": 2,
    "info": 1,
}


def build_dialog_report(
    dialog: DialogEntity,
    *,
    final_score: int,
    deviations_count: int,
    hygiene_results: list[dict],
    deposit_results: list[dict],
    risk_results: list[dict],
    strengths_limit: int,
    improvements_limit: int,
    positive_templates: tuple[str, ...],
    hidden_metric_codes: set[str],
) -> dict:
    """Формирует готовый popup диалога без вычислений во время GET."""
    scored = []
    for item in hygiene_results + deposit_results:
        if item["code"] in hidden_metric_codes:
            continue
        if item["included_in_analytics"]:
            scored.append(item)
    passed = []
    failed = []
    for item in scored:
        if item["score"] == 1:
            passed.append(item)
        else:
            failed.append(item)
    passed.sort(key=_criterion_sort_key)
    failed.sort(key=_criterion_sort_key)
    passed = passed[:strengths_limit]
    failed = failed[:improvements_limit]

    detected_risks = []
    for item in risk_results:
        if item["score"] == 0:
            detected_risks.append(item)
    detected_risks.sort(key=_criterion_sort_key)

    titles_list = []
    for item in passed:
        titles_list.append(item["title_positive"])
    titles = ", ".join(titles_list)
    positive_text = ""
    if titles:
        template_index = int(
            hashlib.sha256(dialog.call_id.encode("utf-8")).hexdigest(),
            16,
        ) % len(positive_templates)
        positive_text = positive_templates[template_index].format(metrics=titles)

    return {
        "callId": dialog.call_id,
        "clientEpk": dialog.client_epk,
        "clientFio": dialog.client_fio or "",
        "clientFioEncrypted": dialog.client_fio_encrypted,
        "occurredAt": dialog.occurred_at.isoformat(),
        "type": "call",
        "score": final_score,
        "deviationsCount": deviations_count,
        "risks": _risk_payloads(detected_risks),
        "strengths": positive_text,
        "improvements": _improvement_payloads(failed),
    }


def _criterion_sort_key(item: dict) -> tuple[int, int, str]:
    return (
        -SEVERITY_ORDER.get(item["severity"], 0),
        -item["penalty"],
        item["code"],
    )


def _risk_payloads(items: list[dict]) -> list[dict]:
    result = []
    for item in items:
        result.append(
            {
                "code": item["code"],
                "title": item["title_negative"],
                "severity": item["severity"],
            }
        )
    return result


def _improvement_payloads(items: list[dict]) -> list[dict]:
    result = []
    for item in items:
        result.append(
            {
                "code": item["code"],
                "title": item["title_negative"],
                "severity": item["severity"],
                "recommendation": item["recommendation"],
                "quote": item["quote"] or "",
            }
        )
    return result
