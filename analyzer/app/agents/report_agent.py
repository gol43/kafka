import logging

from app.agents.gigachat_provider.base import BaseGigaChatProvider
from app.agents.prompt_loader import PromptLoader
from app.schemas.analysis import AggregatedRecommendation

logger = logging.getLogger(__name__)


class ReportAgent:
    """Генерирует только текстовую рекомендацию агрегированного отчёта."""

    def __init__(
        self,
        prompt_loader: PromptLoader,
        provider: BaseGigaChatProvider,
        log_responses: bool = True,
    ) -> None:
        self._prompts = prompt_loader
        self._provider = provider
        self._log_responses = log_responses

    async def build_recommendation(
        self,
        items: list[str],
        report_type: str,
    ) -> str:
        system_prompt, user_prompt = self._prompts.render_aggregate(
            report_type,
            items,
        )
        result = await self._provider.chat_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=AggregatedRecommendation,
        )
        if self._log_responses:
            logger.info("LLM response body=%s", result.model_dump_json())
        return result.summary
