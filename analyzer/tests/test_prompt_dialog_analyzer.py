import asyncio
from datetime import UTC, date, datetime

from app.agents.prompt_loader import PromptLoader
from app.schemas.analysis import CriterionResult, DialogAnalysisResponse
from app.schemas.entities import DialogEntity
from app.services.prompt_dialog_analyzer import PromptDialogAnalyzer


class FakeAgent:
    def __init__(self, prompts: PromptLoader) -> None:
        self.prompts = prompts
        self.calls: list[str] = []

    async def analyze(self, dialog_text: str, block: str) -> DialogAnalysisResponse:
        self.calls.append(block)
        return DialogAnalysisResponse(
            results=[
                CriterionResult(
                    code=item.code,
                    score=0 if item.topic_gate else 1,
                )
                for item in self.prompts.criteria_by_block[block]
            ]
        )


def test_two_requests_and_deposit_exclusion() -> None:
    prompts = PromptLoader(active_criteria_codes={"GENERAL_01"})
    agent = FakeAgent(prompts)
    analyzer = PromptDialogAnalyzer(prompts, agent)
    dialog = DialogEntity(
        call_id="call-1",
        manager_id="00000001",
        work_date=date(2026, 10, 26),
        cleaned_text="Диалог не про вклад",
        required_analyzers=["prompt"],
        created_at=datetime.now(UTC),
    )

    result = asyncio.run(analyzer.analyze(dialog))

    assert agent.calls == ["general", "deposit"]
    assert result.q_score == 100
    assert result.payload["deposit_topic"] is False
    assert all(
        not item["included_in_analytics"]
        for item in result.criteria
        if item["block"] == "deposit"
    )
