from collections import defaultdict
from datetime import date, timedelta
from statistics import median


def quarter_score_state(previous: dict | None, daily: dict, report_date: date) -> dict:
    quarter = (report_date.month - 1) // 3 + 1
    same_period = bool(
        previous
        and previous.get("year") == report_date.year
        and previous.get("quarter") == quarter
    )
    return _score_state(
        previous if same_period else None,
        daily,
        {"year": report_date.year, "quarter": quarter},
    )


def month_score_state(previous: dict | None, daily: dict, report_date: date) -> dict:
    same_period = bool(
        previous
        and previous.get("year") == report_date.year
        and previous.get("month") == report_date.month
    )
    return _score_state(
        previous if same_period else None,
        daily,
        {"year": report_date.year, "month": report_date.month},
    )


def calculate_q_score(
    quarter_state: dict,
    month_state: dict,
    previous_q_score: dict | None,
    report_date: date,
    team_median: float,
    empty_score: int,
) -> dict:
    months = _four_months(previous_q_score, month_state, report_date)
    personal = quarter_state.get("qScore", empty_score)
    return {
        "personal": personal,
        "teamMedian": team_median,
        "months": months,
    }


def team_medians(profiles, current: dict[str, dict], empty_score: int) -> dict:
    by_role = defaultdict(list)
    for profile in profiles:
        quarter = current[profile.manager_id]["quarter"]
        value = quarter.get("qScore", empty_score)
        by_role[profile.role].append(value)

    result = {}
    for role, values in by_role.items():
        result[role] = float(median(values)) if values else float(empty_score)
    return result


def _score_state(previous: dict | None, daily: dict, identity: dict) -> dict:
    score_sum = daily.get("dialogScoreSum", 0)
    dialog_count = daily.get("dialogScoreCount", 0)
    if previous:
        score_sum += previous.get("scoreSum", 0)
        dialog_count += previous.get("dialogCount", 0)

    state = dict(identity)
    state["scoreSum"] = score_sum
    state["dialogCount"] = dialog_count
    state["qScore"] = int(score_sum / dialog_count) if dialog_count else 0
    return state


def _four_months(
    previous_q_score: dict | None,
    current_month: dict,
    report_date: date,
) -> list[dict]:
    known = {}
    if previous_q_score:
        for item in previous_q_score.get("months", []):
            known[(item["year"], item["month"])] = item

    current_key = (current_month["year"], current_month["month"])
    known[current_key] = {
        "year": current_month["year"],
        "month": current_month["month"],
        "qScore": current_month["qScore"],
    }

    result = []
    cursor = report_date.replace(day=1)
    for _ in range(4):
        key = (cursor.year, cursor.month)
        item = known.get(key)
        if item is None:
            item = {"year": cursor.year, "month": cursor.month, "qScore": 0}
        result.append(item)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    return result
