import logging
from collections.abc import Awaitable, Callable

from app.agents.external_analyzer_agent import ExternalAnalyzerAgent
from app.config import Settings
from app.database.repositories.dialog_repository import DialogRepository
from app.exceptions import EntityNotFoundError
from app.schemas.analyzer_steps import AnalyzerStepResult
from app.schemas.entities import DialogEntity
from app.services.dialog_analysis.dialog_report_builder import build_dialog_report
from app.services.dialog_analysis.prompt_dialog_analyzer import PromptDialogAnalyzer

logger = logging.getLogger(__name__)


class DialogAnalysisOrchestrator:
    """Последовательно запускает обязательные независимые анализаторы."""

    def __init__(
        self,
        repository: DialogRepository,
        prompt_analyzer: PromptDialogAnalyzer,
        external_analyzers: dict[str, ExternalAnalyzerAgent],
        settings: Settings,
        positive_templates: tuple[str, ...],
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._positive_templates = positive_templates
        self._steps: dict[
            str,
            Callable[[DialogEntity], Awaitable[AnalyzerStepResult]],
        ] = {"prompt": prompt_analyzer.analyze}
        for name, agent in external_analyzers.items():
            self._steps[name] = self._external_step(agent)

    async def process(self, call_id: str) -> None:
        dialog = await self._repository.get(call_id)
        if dialog is None:
            raise EntityNotFoundError("Диалог не найден")

        logger.info("Dialog analysis started call_id=%s", call_id)
        step_results: dict[str, dict] = {}
        prompt_result: AnalyzerStepResult | None = None

        for analyzer_name in dialog.required_analyzers:
            step = self._steps.get(analyzer_name)
            if step is None:
                raise ValueError(f"Анализатор не зарегистрирован: {analyzer_name}")

            logger.info("Agent started call_id=%s name=%s", call_id, analyzer_name)
            result = await step(dialog)
            logger.info("Agent response received call_id=%s name=%s", call_id, analyzer_name)
            step_results[analyzer_name] = result.payload
            if analyzer_name == "prompt":
                prompt_result = result

        if prompt_result is None:
            raise ValueError("Для диалога не выполнен обязательный Prompt Analyzer")

        prompt = prompt_result.payload
        report_payload = build_dialog_report(
            dialog,
            final_score=float(prompt["score"]),
            deviations_count=int(prompt["deviations_count"]),
            hygiene_results=prompt["hygiene_results"],
            deposit_results=prompt["deposit_results"],
            risk_results=prompt["risk_results"],
            strengths_limit=self._settings.strengths_limit,
            improvements_limit=self._settings.improvements_limit,
            positive_templates=self._positive_templates,
        )

        await self._repository.complete_analysis(
            call_id=call_id,
            hygiene_results=prompt["hygiene_results"],
            deposit_results=prompt["deposit_results"],
            risk_results=prompt["risk_results"],
            audio_results=step_results.get("audio", {}),
            factor_results=step_results.get("factor", {}),
            general_score=float(prompt["general_score"]),
            deposit_score=prompt["deposit_score"],
            score=float(prompt["score"]),
            deposit_topic=bool(prompt["deposit_topic"]),
            critical_violation=prompt_result.critical_violation,
            deviations_count=int(prompt["deviations_count"]),
            risks_count=int(prompt["risks_count"]),
            report_payload=report_payload,
        )
        logger.info("Dialog result saved call_id=%s", call_id)

    @staticmethod
    def _external_step(
        agent: ExternalAnalyzerAgent,
    ) -> Callable[[DialogEntity], Awaitable[AnalyzerStepResult]]:
        async def run(dialog: DialogEntity) -> AnalyzerStepResult:
            result = await agent.analyze(
                {
                    "call_id": dialog.call_id,
                    "manager_id": dialog.manager_id,
                    "client_epk": dialog.client_epk,
                    "work_date": str(dialog.work_date),
                    "cleaned_text": dialog.cleaned_text,
                }
            )
            return AnalyzerStepResult(analyzer=agent.name, payload=result)

        return run
