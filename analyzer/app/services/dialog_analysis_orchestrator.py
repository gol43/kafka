import logging
from collections.abc import Awaitable, Callable

from app.agents.external_analyzer_agent import ExternalAnalyzerAgent
from app.database.repositories.dialog_repository import DialogRepository
from app.exceptions import EntityNotFoundError
from app.schemas.analyzer_steps import AnalyzerStepResult
from app.schemas.entities import DialogEntity
from app.services.prompt_dialog_analyzer import PromptDialogAnalyzer
from app.services.dialog_report_builder import build_dialog_report
from app.config import Settings

logger = logging.getLogger(__name__)


class DialogAnalysisOrchestrator:
    """Последовательно запускает обязательные анализаторы одного диалога.

    Диалог становится `completed` только после успешного завершения каждого
    анализатора из `required_analyzers`. При первой ошибке цепочка прерывается.
    """

    def __init__(
        self,
        repository: DialogRepository,
        prompt_analyzer: PromptDialogAnalyzer,
        external_analyzers: dict[str, ExternalAnalyzerAgent],
        settings: Settings | None = None,
        positive_templates: tuple[str, ...] = (),
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
        """Запускает цепочку и одним обновлением сохраняет полный результат."""

        dialog = await self._repository.get(call_id)
        if dialog is None:
            raise EntityNotFoundError("Диалог не найден")

        await self._repository.mark_processing(call_id)
        logger.info("Dialog analysis started call_id=%s", call_id)

        results: dict[str, dict] = {}
        q_score: float | None = None
        critical_violation = False

        for analyzer_name in dialog.required_analyzers:
            step = self._steps.get(analyzer_name)
            if step is None:
                raise ValueError(f"Анализатор не зарегистрирован: {analyzer_name}")

            logger.info("Agent started call_id=%s name=%s", call_id, analyzer_name)
            result = await step(dialog)
            logger.info(
                "Agent response received call_id=%s name=%s", call_id, analyzer_name
            )
            results[analyzer_name] = result.payload
            if result.q_score is not None:
                q_score = result.q_score
            critical_violation = critical_violation or result.critical_violation

        await self._repository.complete_analysis(
            call_id=call_id,
            analysis_results=results,
            q_score=q_score,
            critical_violation=critical_violation,
            criteria=results.get("prompt", {}).get("criteria", []),
            dialog_report=self._build_report(dialog, q_score, results),
            general_score=results.get("prompt", {}).get("general_score"),
            deposit_topic=results.get("prompt", {}).get("deposit_topic", False),
            deposit_score=results.get("prompt", {}).get("deposit_score"),
            deviations_count=results.get("prompt", {}).get("deviations_count", 0),
        )
        logger.info("Dialog result saved call_id=%s", call_id)

    def _build_report(self, dialog, q_score, results) -> dict:
        criteria = results.get("prompt", {}).get("criteria", [])
        if (
            not criteria
            or "included_in_analytics" not in criteria[0]
            or not self._positive_templates
        ):
            return {}
        return build_dialog_report(
            dialog,
            final_score=q_score or 0,
            deviations_count=results.get("prompt", {}).get("deviations_count", 0),
            criteria=criteria,
            strengths_limit=self._settings.strengths_limit if self._settings else 3,
            improvements_limit=self._settings.improvements_limit if self._settings else 3,
            positive_templates=self._positive_templates,
        )

    @staticmethod
    def _external_step(
        agent: ExternalAnalyzerAgent,
    ) -> Callable[[DialogEntity], Awaitable[AnalyzerStepResult]]:
        async def run(dialog: DialogEntity) -> AnalyzerStepResult:
            result = await agent.analyze(
                {
                    "call_id": dialog.call_id,
                    "manager_id": dialog.manager_id,
                    "work_date": str(dialog.work_date),
                    "cleaned_text": dialog.cleaned_text,
                    "dialog_data": dialog.dialog_data,
                }
            )
            return AnalyzerStepResult(analyzer=agent.name, payload=result)

        return run
