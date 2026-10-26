import hashlib

from app.schemas.entities import DialogEntity

SEVERITY_ORDER = {
    "fraud": 5,
    "critical": 4,
    "significant": 3,
    "minor": 2,
    "info": 1,
}

def build_dialog_report(
    dialog: DialogEntity,
    *,
    final_score: float,
    deviations_count: int,
    criteria: list[dict],
    strengths_limit: int,
    improvements_limit: int,
    positive_templates: tuple[str, ...],
) -> dict:
    """Формирует готовую карточку звонка без вычислений во время GET."""

    included = [item for item in criteria if item["included_in_analytics"]]
    passed = sorted(
        (item for item in included if item["score"] == 1),
        key=_criterion_sort_key,
    )[:strengths_limit]
    failed = sorted(
        (item for item in included if item["score"] == 0),
        key=_criterion_sort_key,
    )[:improvements_limit]

    titles = ", ".join(item["title"] for item in passed)
    positive_text = ""
    if titles:
        template_index = int(
            hashlib.sha256(dialog.call_id.encode("utf-8")).hexdigest(),
            16,
        ) % len(positive_templates)
        positive_text = positive_templates[template_index].format(metrics=titles)

    return {
        "callId": dialog.call_id,
        "clientFio": dialog.client_fio,
        "occurredAt": dialog.occurred_at.isoformat() if dialog.occurred_at else None,
        "type": "call",
        "score": final_score,
        "deviationsCount": deviations_count,
        "strengths": {
            "text": positive_text,
            "metrics": [
                {"code": item["code"], "title": item["title"]}
                for item in passed
            ],
        },
        "improvements": [
            {
                "code": item["code"],
                "title": item["title"],
                "severity": item["severity"],
                "recommendation": item["recommendation"],
                "quote": item["quote"],
            }
            for item in failed
        ],
    }


def _criterion_sort_key(item: dict) -> tuple[int, int, str]:
    return (
        -SEVERITY_ORDER.get(item["severity"], 0),
        -item["penalty"],
        item["code"],
    )
