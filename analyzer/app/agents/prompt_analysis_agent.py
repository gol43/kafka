import asyncio
import logging

from app.agents.gigachat_provider.base import BaseGigaChatProvider
from app.agents.prompt_loader import PromptLoader
from app.exceptions import InvalidAnalysisResultError
from app.schemas.analysis import DialogAnalysisResponse, create_block_response_model

logger = logging.getLogger(__name__)


class PromptAnalysisAgent:
    """Формирует промпт диалога и валидирует структурированный ответ модели."""

    def __init__(
        self,
        prompt_loader: PromptLoader,
        provider: BaseGigaChatProvider,
        block: str,
        log_responses: bool = True,
        validation_max_attempts: int = 3,
        validation_retry_seconds: float = 1,
    ) -> None:
        self._prompts = prompt_loader
        self._provider = provider
        self._block = block
        self._log_responses = log_responses
        self._validation_max_attempts = validation_max_attempts
        self._validation_retry_seconds = validation_retry_seconds
        codes = []
        for criterion in self._prompts.criteria_by_block.get(block, ()):
            codes.append(criterion.code)
        self._response_model = create_block_response_model(block, tuple(codes))

    async def analyze(self, dialog_text: str) -> DialogAnalysisResponse:
        system_prompt, user_prompt = self._prompts.render_dialog(
            dialog_text,
            self._block,
        )
        last_error = None
        for attempt in range(1, self._validation_max_attempts + 1):
            raw_result = await self._provider.chat_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=self._response_model,
            )
            result = DialogAnalysisResponse.model_validate(raw_result.model_dump())
            result = self._normalize_quotes(result)
            if self._log_responses:
                logger.info("LLM response body=%s", result.model_dump_json())
            try:
                self._validate_result(result, dialog_text, self._block)
                return result
            except InvalidAnalysisResultError as exc:
                last_error = exc
                logger.warning(
                    "LLM response validation failed block=%s attempt=%s error=%s",
                    self._block,
                    attempt,
                    exc,
                )
                if attempt < self._validation_max_attempts:
                    await asyncio.sleep(self._validation_retry_seconds)
        raise last_error

    def _normalize_quotes(
        self,
        result: DialogAnalysisResponse,
    ) -> DialogAnalysisResponse:
        normalized_results = []
        for item in result.results:
            definition = self._prompts.criteria_by_code.get(item.code)
            quote_allowed = bool(
                definition
                and definition.quote_required
                and item.score == 0
            )
            normalized_results.append(
                item if quote_allowed else item.model_copy(update={"quote": None})
            )
        return result.model_copy(update={"results": normalized_results})

    def _validate_result(
        self,
        result: DialogAnalysisResponse,
        dialog_text: str,
        block: str,
    ) -> None:
        received_codes = []
        for item in result.results:
            received_codes.append(item.code)
        expected_codes = set()
        for item in self._prompts.criteria_by_block.get(block, ()):
            expected_codes.add(item.code)

        if len(received_codes) != len(set(received_codes)):
            raise InvalidAnalysisResultError(
                "GigaChat вернул повторяющиеся коды критериев"
            )
        received_codes_set = set(received_codes)
        if received_codes_set != expected_codes:
            missing_codes = sorted(expected_codes - received_codes_set)
            extra_codes = sorted(received_codes_set - expected_codes)
            raise InvalidAnalysisResultError(
                "Набор критериев GigaChat не совпадает с каталогом промптов: "
                f"missing={missing_codes}, extra={extra_codes}, "
                f"received={sorted(received_codes_set)}"
            )

        for item in result.results:
            if item.score == 1:
                continue
            definition = self._prompts.criteria_by_code[item.code]
            if not definition.quote_required:
                continue
            if not item.quote:
                raise InvalidAnalysisResultError(
                    f"Для нарушения {item.code} требуется цитата"
                )
            if item.quote not in dialog_text:
                raise InvalidAnalysisResultError(
                    f"В результате {item.code} нет точной цитаты из диалога"
                )
