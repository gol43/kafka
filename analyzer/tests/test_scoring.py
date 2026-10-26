from types import SimpleNamespace

import pytest

from app.agents.prompt_analysis_agent import PromptAnalysisAgent
from app.exceptions import InvalidAnalysisResultError
from app.schemas.analysis import CriterionResult, DialogAnalysisResponse
from app.schemas.criteria import CriterionDefinition
from app.services.scoring import calculate_dialog_score, calculate_q_score, weighted_q_score

CRITERIA = {
    "A": CriterionDefinition(
        code="A",
        title="A",
        description="",
        rules="",
        trigger="",
        positive_definition="",
        negative_definition="",
        output_rule="",
        penalty=12,
        critical=True,
    ),
    "B": CriterionDefinition(
        code="B",
        title="B",
        description="",
        rules="",
        trigger="",
        positive_definition="",
        negative_definition="",
        output_rule="",
        penalty=5,
        critical=False,
    ),
}


def test_q_score_and_critical_cap() -> None:
    result = calculate_q_score(
        [
            CriterionResult(code="A", score=0, quote="нарушение"),
            CriterionResult(code="B", score=1),
        ],
        CRITERIA,
    )
    assert result.q_score == 80


def test_weighted_score_uses_communication_count() -> None:
    assert weighted_q_score([(100, 1), (1500, 30)]) == 1600 / 31


def test_violation_requires_exact_dialog_quote() -> None:
    agent = PromptAnalysisAgent.__new__(PromptAnalysisAgent)
    agent._prompts = SimpleNamespace(
        criteria_by_block={"general": (CRITERIA["A"],)}
    )

    valid = DialogAnalysisResponse(
        results=[
            CriterionResult(
                code="A",
                score=0,
                quote="это невозможно",
            )
        ]
    )
    agent._validate_result(valid, "Клиент спросил. Менеджер: это невозможно", "general")

    invalid = DialogAnalysisResponse(
        results=[
            CriterionResult(
                code="A",
                score=0,
                quote="другая цитата",
            )
        ]
    )
    with pytest.raises(InvalidAnalysisResultError, match="точной цитаты"):
        agent._validate_result(invalid, "Менеджер: это невозможно", "general")


def test_missing_quote_is_allowed_when_text_has_no_exact_fragment() -> None:
    assert CriterionResult(code="A", score=0).quote is None


def test_deposit_topic_false_excludes_deposit_block() -> None:
    topic = CriterionDefinition(
        code="TOPIC",
        title="Тема",
        description="",
        rules="",
        trigger="",
        positive_definition="",
        negative_definition="",
        output_rule="",
        penalty=0,
        critical=False,
        block="deposit",
        topic_gate=True,
    )
    deposit = CriterionDefinition(
        code="DEP",
        title="Вклад",
        description="",
        rules="",
        trigger="",
        positive_definition="",
        negative_definition="",
        output_rule="",
        penalty=100,
        critical=True,
        block="deposit",
        severity="fraud",
    )
    result = calculate_dialog_score(
        [CriterionResult(code="B", score=1)],
        [CriterionResult(code="TOPIC", score=0), CriterionResult(code="DEP", score=0)],
        {"B": CRITERIA["B"], "TOPIC": topic, "DEP": deposit},
    )
    assert result.final_score == 100
    assert result.deposit_score is None
    assert result.deposit_topic is False
