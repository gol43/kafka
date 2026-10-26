import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from pydantic import ValidationError

from app.agents.gigachat_provider.base import BaseGigaChatProvider, ResponseModel
from app.agents.gigachat_provider.exceptions import GigaChatError
from app.config import Settings

Result = TypeVar("Result")


class OllamaProvider(BaseGigaChatProvider):
    """Бесплатный локальный LLM-провайдер для ручного E2E-тестирования."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.gigachat_max_concurrency)
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_base_url.rstrip("/"),
            timeout=settings.gigachat_timeout_seconds,
        )

    async def chat_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
    ) -> ResponseModel:
        """Запрашивает у Ollama ответ, ограниченный Pydantic JSON Schema."""

        async def operation() -> ResponseModel:
            options: dict = {
                "num_predict": self._settings.gigachat_max_output_tokens,
                "repeat_penalty": self._settings.gigachat_repetition_penalty,
                "num_ctx": self._settings.gigachat_max_input_tokens,
            }
            if self._settings.gigachat_temperature is not None:
                options["temperature"] = self._settings.gigachat_temperature
            if self._settings.gigachat_top_p is not None:
                options["top_p"] = self._settings.gigachat_top_p

            response = await self._client.post(
                "/api/chat",
                json={
                    "model": self._settings.ollama_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "think": False,
                    "format": response_model.model_json_schema(),
                    "keep_alive": self._settings.ollama_keep_alive,
                    "options": options,
                },
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            return response_model.model_validate_json(content)

        async with self._semaphore:
            return await self._with_attempts(operation)

    async def count_tokens(self, values: list[str]) -> int:
        """Консервативно оценивает токены без отдельной генерации в Ollama."""

        characters = sum(len(value) for value in values)
        return max(1, math.ceil(characters / self._settings.ollama_chars_per_token))

    async def close(self) -> None:
        """Закрывает общий HTTP connection pool."""

        await self._client.aclose()

    async def _with_attempts(
        self,
        operation: Callable[[], Awaitable[Result]],
    ) -> Result:
        last_error: Exception | None = None

        for attempt in range(1, self._settings.gigachat_max_attempts + 1):
            try:
                return await operation()
            except (
                httpx.HTTPError,
                KeyError,
                ValueError,
                ValidationError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                if attempt >= self._settings.gigachat_max_attempts:
                    break
                delay = min(
                    self._settings.gigachat_retry_base_seconds * 2 ** (attempt - 1),
                    20,
                )
                await asyncio.sleep(delay)

        raise GigaChatError(
            "Локальная Ollama не вернула корректный ответ после всех попыток",
            attempts=self._settings.gigachat_max_attempts,
        ) from last_error
