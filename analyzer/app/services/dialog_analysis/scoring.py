from dataclasses import dataclass

from app.schemas.analysis import CriterionResult
from app.schemas.criteria import CriterionDefinition


@dataclass(frozen=True, slots=True)
class ScoreResult:
    q_score: int
    penalty_sum: int
    critical_violation: bool


@dataclass(frozen=True, slots=True)
class DialogScoreResult:
    final_score: int
    hygiene_score: int
    deposit_score: int | None
    deposit_topic: bool
    critical_violation: bool
    deviations_count: int


def calculate_q_score(
    results: list[CriterionResult],
    criteria: dict[str, CriterionDefinition],
) -> ScoreResult:
    violations = []
    for result in results:
        if result.score == 0:
            violations.append(result)

    penalty_sum = 0
    critical_violation = False
    for violation in violations:
        definition = criteria[violation.code]
        penalty_sum += definition.penalty
        if definition.severity == "critical":
            critical_violation = True

    q_score = max(0, 100 - penalty_sum)
    if critical_violation:
        q_score = min(q_score, 80)

    return ScoreResult(
        q_score=q_score,
        penalty_sum=penalty_sum,
        critical_violation=critical_violation,
    )


def calculate_dialog_score(
    general_results: list[CriterionResult],
    deposit_results: list[CriterionResult],
    criteria: dict[str, CriterionDefinition],
    critical_score_cap: int = 80,
) -> DialogScoreResult:
    """Считает итог звонка только из штрафов каталога, без участия LLM."""
    general = calculate_q_score(general_results, criteria)
    topic_result = None
    for item in deposit_results:
        if item.code == "DEPOSIT_TOPIC":
            topic_result = item
            break
    if topic_result is None:
        raise ValueError("В блоке вкладов отсутствует критерий темы")

    deposit_topic = topic_result.score == 1
    included_deposit_results = []
    for item in deposit_results:
        if item.code != "DEPOSIT_TOPIC":
            included_deposit_results.append(item)

    if not deposit_topic:
        deviations_count = 0
        for item in general_results:
            if item.score == 0:
                deviations_count += 1
        return DialogScoreResult(
            final_score=general.q_score,
            hygiene_score=general.q_score,
            deposit_score=None,
            deposit_topic=False,
            critical_violation=general.critical_violation,
            deviations_count=deviations_count,
        )

    deposit = calculate_q_score(included_deposit_results, criteria)
    final_score = _round_score((general.q_score + deposit.q_score) / 2)
    critical_violation = general.critical_violation or deposit.critical_violation
    if critical_violation:
        final_score = min(final_score, critical_score_cap)

    deviations_count = 0
    for item in general_results:
        if item.score == 0:
            deviations_count += 1
    for item in included_deposit_results:
        if item.score == 0:
            deviations_count += 1

    return DialogScoreResult(
        final_score=final_score,
        hygiene_score=general.q_score,
        deposit_score=deposit.q_score,
        deposit_topic=True,
        critical_violation=critical_violation,
        deviations_count=deviations_count,
    )


def _round_score(value: float) -> int:
    return int(value + 0.5)
