import logging

from app.agents.prompt_analysis_agent import PromptAnalysisAgent
from app.agents.prompt_loader import PromptLoader
from app.config import Settings
from app.schemas.analysis import CriterionResult, DialogAnalysisResponse
from app.schemas.analyzer_steps import AnalyzerStepResult
from app.schemas.entities import DialogEntity
from app.services.dialog_analysis.scoring import calculate_dialog_score

logger = logging.getLogger(__name__)


class PromptDialogAnalyzer:
    """Явно запускает три независимых prompt-анализа одного диалога."""

    name = "prompt"

    def __init__(
        self,
        prompt_loader: PromptLoader,
        hygiene_agent: PromptAnalysisAgent,
        deposit_agent: PromptAnalysisAgent,
        risk_agent: PromptAnalysisAgent,
        settings: Settings,
    ) -> None:
        self._prompts = prompt_loader
        self._hygiene_agent = hygiene_agent
        self._deposit_agent = deposit_agent
        self._risk_agent = risk_agent
        self._critical_score_cap = settings.critical_score_cap
        self._deposit_enabled = settings.deposit_analysis_enabled

    async def analyze(self, dialog: DialogEntity) -> AnalyzerStepResult:
        """Последовательно выполняет гигиену, вклады и независимые риски."""

        logger.info("Hygiene analysis started call_id=%s", dialog.call_id)
        hygiene_response = await self._hygiene_agent.analyze(dialog.cleaned_text)
        logger.info("Hygiene analysis completed call_id=%s", dialog.call_id)

        logger.info("Deposit analysis started call_id=%s", dialog.call_id)
        deposit_response = (
            await self._deposit_agent.analyze(dialog.cleaned_text)
            if self._deposit_enabled
            else DialogAnalysisResponse(
                results=[CriterionResult(code="DEPOSIT_TOPIC", score=0)]
            )
        )
        logger.info("Deposit analysis completed call_id=%s", dialog.call_id)

        logger.info("Risk analysis started call_id=%s", dialog.call_id)
        risk_response = await self._risk_agent.analyze(dialog.cleaned_text)
        logger.info("Risk analysis completed call_id=%s", dialog.call_id)

        score = calculate_dialog_score(
            hygiene_response.results,
            deposit_response.results,
            self._prompts.criteria_by_code,
            self._critical_score_cap,
        )

        hygiene_results = [
            self._enrich(item, included=True)
            for item in hygiene_response.results
        ]
        deposit_results = [
            self._enrich(
                item.model_copy(
                    update={"score": item.score if score.deposit_topic else 0}
                ),
                included=score.deposit_topic,
            )
            for item in deposit_response.results
        ]
        risk_results = [
            self._enrich(item, included=True)
            for item in risk_response.results
        ]

        risks_count = sum(item["score"] == 0 for item in risk_results)
        criteria = hygiene_results + deposit_results

        return AnalyzerStepResult(
            analyzer=self.name,
            payload={
                "hygiene_results": hygiene_results,
                "deposit_results": deposit_results,
                "risk_results": risk_results,
                "general_score": score.general_score,
                "deposit_topic": score.deposit_topic,
                "deposit_score": score.deposit_score,
                "score": score.final_score,
                "deviations_count": score.deviations_count,
                "risks_count": risks_count,
            },
            q_score=score.final_score,
            critical_violation=score.critical_violation,
            criteria=criteria,
        )

    def _enrich(self, result: CriterionResult, *, included: bool) -> dict:
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
