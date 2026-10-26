import logging
from app.agents.gigachat_provider.base import BaseGigaChatProvider
from app.agents.prompt_loader import PromptLoader
from app.exceptions import InvalidAnalysisResultError
from app.schemas.analysis import DialogAnalysisResponse

logger = logging.getLogger(__name__)


class PromptAnalysisAgent:
    """Формирует промпт диалога и валидирует структурированный ответ модели."""

    def __init__(
        self,
        prompt_loader: PromptLoader,
        provider: BaseGigaChatProvider,
        log_responses: bool = True,
    ) -> None:
        self._prompts = prompt_loader
        self._provider = provider
        self._log_responses = log_responses

    async def analyze(self, dialog_text: str, block: str) -> DialogAnalysisResponse:
        system_prompt, user_prompt = self._prompts.render_dialog(dialog_text, block)
        result = await self._provider.chat_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=DialogAnalysisResponse,
        )
        if self._log_responses:
            logger.info("LLM response body=%s", result.model_dump_json())
        self._validate_result(result, dialog_text, block)
        return result

    def _validate_result(
        self,
        result: DialogAnalysisResponse,
        dialog_text: str,
        block: str,
    ) -> None:
        received_codes = [item.code for item in result.results]
        expected_codes = {
            item.code for item in self._prompts.criteria_by_block.get(block, ())
        }

        if len(received_codes) != len(set(received_codes)):
            raise InvalidAnalysisResultError(
                "GigaChat вернул повторяющиеся коды критериев"
            )
        if set(received_codes) != expected_codes:
            raise InvalidAnalysisResultError(
                "Набор критериев GigaChat не совпадает с каталогом промптов"
            )

        for item in result.results:
            if item.score == 1 or item.quote is None:
                continue
            if item.quote not in dialog_text:
                raise InvalidAnalysisResultError(
                    f"В результате {item.code} нет точной цитаты из диалога"
                )
