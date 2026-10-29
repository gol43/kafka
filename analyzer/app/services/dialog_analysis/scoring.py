from dataclasses import dataclass

from app.schemas.analysis import CriterionResult
from app.schemas.criteria import CriterionDefinition


@dataclass(frozen=True, slots=True)
class ScoreResult:
    q_score: float
    penalty_sum: int
    critical_violation: bool


@dataclass(frozen=True, slots=True)
class DialogScoreResult:
    final_score: float
    general_score: float
    deposit_score: float | None
    deposit_topic: bool
    critical_violation: bool
    deviations_count: int


def calculate_q_score(
    results: list[CriterionResult],
    criteria: dict[str, CriterionDefinition],
) -> ScoreResult:
    violations = [result for result in results if result.score == 0]
    penalty_sum = sum(criteria[result.code].penalty for result in violations)
    critical_violation = any(criteria[result.code].critical for result in violations)

    q_score = float(max(0, 100 - penalty_sum))
    if critical_violation:
        q_score = min(q_score, 80.0)

    return ScoreResult(
        q_score=q_score,
        penalty_sum=penalty_sum,
        critical_violation=critical_violation,
    )


def weighted_q_score(items: list[tuple[float, int]]) -> float | None:
    total_count = sum(count for _, count in items)
    if total_count == 0:
        return None
    return sum(score_sum for score_sum, _ in items) / total_count


def calculate_dialog_score(
    general_results: list[CriterionResult],
    deposit_results: list[CriterionResult],
    criteria: dict[str, CriterionDefinition],
    critical_score_cap: float = 80.0,
) -> DialogScoreResult:
    """Считает итог звонка только из штрафов каталога, без участия LLM."""

    general = calculate_q_score(general_results, criteria)
    topic_result = next(
        (
            item
            for item in deposit_results
            if criteria[item.code].topic_gate
        ),
        None,
    )
    if topic_result is None:
        raise ValueError("В блоке вкладов отсутствует критерий темы")

    deposit_topic = topic_result.score == 1
    included_deposit_results = [
        item
        for item in deposit_results
        if not criteria[item.code].topic_gate
    ]

    if not deposit_topic:
        return DialogScoreResult(
            final_score=general.q_score,
            general_score=general.q_score,
            deposit_score=None,
            deposit_topic=False,
            critical_violation=general.critical_violation,
            deviations_count=sum(item.score == 0 for item in general_results),
        )

    deposit = calculate_q_score(included_deposit_results, criteria)
    final_score = (general.q_score + deposit.q_score) / 2
    critical_violation = general.critical_violation or deposit.critical_violation
    if critical_violation:
        final_score = min(final_score, critical_score_cap)

    return DialogScoreResult(
        final_score=final_score,
        general_score=general.q_score,
        deposit_score=deposit.q_score,
        deposit_topic=True,
        critical_violation=critical_violation,
        deviations_count=sum(item.score == 0 for item in general_results)
        + sum(item.score == 0 for item in included_deposit_results),
    )
