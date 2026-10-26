from datetime import UTC, date, datetime

import pytest

from app.schemas.analyzer_steps import AnalyzerStepResult
from app.schemas.entities import DialogEntity
from app.services.dialog_analysis_orchestrator import DialogAnalysisOrchestrator


class FakeRepository:
    def __init__(self) -> None:
        self.dialog = DialogEntity(
            call_id="call-1",
            manager_id="00000001",
            work_date=date(2026, 10, 22),
            cleaned_text="Сотрудник: Добрый день",
            required_analyzers=["prompt", "audio", "faq"],
            created_at=datetime.now(UTC),
        )
        self.events: list[str] = []
        self.saved: dict | None = None

    async def get(self, call_id: str):
        return self.dialog

    async def mark_processing(self, call_id: str) -> None:
        self.events.append("processing")

    async def complete_analysis(self, **values) -> None:
        self.events.append("completed")
        self.saved = values


class FakePromptAnalyzer:
    def __init__(self, repository: FakeRepository) -> None:
        self._repository = repository

    async def analyze(self, dialog) -> AnalyzerStepResult:
        self._repository.events.append("prompt")
        return AnalyzerStepResult(
            analyzer="prompt",
            payload={
                "criteria": [{"code": "A", "score": 1, "recommendation": "Хорошо"}]
            },
            q_score=91,
            criteria=[{"code": "A", "score": 1, "recommendation": "Хорошо"}],
        )


class FakeExternalAnalyzer:
    def __init__(self, name: str, repository: FakeRepository) -> None:
        self.name = name
        self._repository = repository

    async def analyze(self, dialog) -> dict:
        self._repository.events.append(self.name)
        return {"ok": True}


@pytest.mark.asyncio
async def test_analyzers_run_sequentially_and_save_once() -> None:
    repository = FakeRepository()
    orchestrator = DialogAnalysisOrchestrator(
        repository=repository,
        prompt_analyzer=FakePromptAnalyzer(repository),
        external_analyzers={
            "audio": FakeExternalAnalyzer("audio", repository),
            "faq": FakeExternalAnalyzer("faq", repository),
        },
    )

    await orchestrator.process("call-1")

    assert repository.events == [
        "processing",
        "prompt",
        "audio",
        "faq",
        "completed",
    ]
    assert repository.saved["q_score"] == 91
    assert set(repository.saved["analysis_results"]) == {"prompt", "audio", "faq"}
