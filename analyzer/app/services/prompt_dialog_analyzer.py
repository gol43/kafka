from app.agents.prompt_analysis_agent import PromptAnalysisAgent
from app.agents.prompt_loader import PromptLoader
from app.schemas.analyzer_steps import AnalyzerStepResult
from app.schemas.analysis import CriterionResult, DialogAnalysisResponse
from app.schemas.entities import DialogEntity
from app.services.scoring import calculate_dialog_score
from app.config import Settings


class PromptDialogAnalyzer:
    """Выполняет Prompt-анализ одного диалога и считает его Q-score."""

    name = "prompt"

    def __init__(
        self,
        prompt_loader: PromptLoader,
        agent: PromptAnalysisAgent,
        settings: Settings | None = None,
    ) -> None:
        self._prompts = prompt_loader
        self._agent = agent
        self._critical_score_cap = settings.critical_score_cap if settings else 80.0
        self._deposit_enabled = settings.deposit_analysis_enabled if settings else True

    async def analyze(self, dialog: DialogEntity) -> AnalyzerStepResult:
        """Отправляет текст в LLM и проверяет все активные критерии."""

        general_response = await self._agent.analyze(dialog.cleaned_text, "general")
        deposit_response = (
            await self._agent.analyze(dialog.cleaned_text, "deposit")
            if self._deposit_enabled
            else DialogAnalysisResponse(
                results=[CriterionResult(code="DEPOSIT_TOPIC", score=0)]
            )
        )
        score = calculate_dialog_score(
            general_response.results,
            deposit_response.results,
            self._prompts.criteria_by_code,
            self._critical_score_cap,
        )

        criteria = []
        for item in general_response.results:
            criteria.append(self._enrich(item, included=True))

        for item in deposit_response.results:
            normalized = item.model_copy(
                update={"score": item.score if score.deposit_topic else 0}
            )
            criteria.append(self._enrich(normalized, included=score.deposit_topic))

        return AnalyzerStepResult(
            analyzer=self.name,
            payload={
                "criteria": criteria,
                "general_score": score.general_score,
                "deposit_topic": score.deposit_topic,
                "deposit_score": score.deposit_score,
                "deviations_count": score.deviations_count,
            },
            q_score=score.final_score,
            critical_violation=score.critical_violation,
            criteria=criteria,
        )

    def _enrich(self, result, *, included: bool) -> dict:
        definition = self._prompts.criteria_by_code[result.code]
        severity = definition.severity
        if severity == "minor" and definition.critical:
            severity = "critical"
        elif severity == "minor" and definition.penalty >= 5:
            severity = "significant"

        return {
            "code": result.code,
            "title": definition.title,
            "block": definition.block,
            "score": result.score,
            "quote": result.quote,
            "severity": severity,
            "penalty": definition.penalty,
            "critical": definition.critical,
            "quote_required": definition.quote_required,
            "recommendation": definition.recommendation or definition.output_rule,
            "included_in_analytics": included and not definition.topic_gate,
        }
