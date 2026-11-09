import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import TypeVar, cast

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_gigachat.chat_models import GigaChat
from pydantic import BaseModel

from app.agents.gigachat_provider.base import BaseGigaChatProvider, ResponseModel
from app.agents.gigachat_provider.exceptions import (
    GigaChatError,
    map_gigachat_error,
)
from app.config import Settings

logger = logging.getLogger(__name__)

Struct = TypeVar("Struct", bound=BaseModel)

class GigaChatProvider(BaseGigaChatProvider):
    """Провайдер GigaChat на основе langchain-gigachat с мутуальной TLS и structured output."""

    def __init__(self, settings: Settings) -> None:
        """Инициализация провайдера.

        :param settings: настройки Analyzer (ENV-переменные).
        """
        self._base_url = settings.gigachat_base_url
        self._retry_limit = settings.gigachat_max_attempts
        self._retry_delay = settings.gigachat_retry_base_seconds
        self._request_timeout = settings.gigachat_timeout_seconds
        self._model = settings.gigachat_model
        self._scope = settings.gigachat_scope
        self._temperature = settings.gigachat_temperature
        self._verify_ssl = settings.gigachat_verify_ssl
        self._cert_file = settings.gigachat_cert_file
        self._key_file = settings.gigachat_key_file

        self._semaphore = asyncio.Semaphore(settings.gigachat_max_concurrency)

    @lru_cache(maxsize=10)
    def get_client(self, model: str | None = None) -> GigaChat:
        """Кэширует клиент по модели - нет нового создания на каждый запрос.

        Сертификаты, base_url и verify_ssl_certs передаются явно.
        GIGACHAT_CREDENTIALS и GIGACHAT_SCOPE читаются из ENV автоматически.
        """
        kwargs: dict = {
            "model": model or self._model,
            "scope": self._scope,
            "temperature": self._temperature,
            "timeout": self._request_timeout,
            "verify_ssl_certs": self._verify_ssl,
            "base_url": self._base_url,
        }
        if self._cert_file:
            kwargs["cert_file"] = self._cert_file
        if self._key_file:
            kwargs["key_file"] = self._key_file

        return GigaChat(**kwargs)

    async def chat_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
    ) -> ResponseModel:
        """Вызов LLM со строгой схемой ответа."""

        async def operation() -> ResponseModel:
            messages: list[BaseMessage] = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            gc_model = self.get_client()
            gc_model_structured = gc_model.with_structured_output(
                schema=response_model,
                method="json_schema",
                strict=True,
            )
            result = cast(
                ResponseModel,
                await gc_model_structured.ainvoke(messages),
            )
            if result is None:
                raise ValueError("GigaChat returned None")
            return result

        return await self._with_retry(operation)

    async def close(self) -> None:
        self.get_client.cache_clear()

    async def _with_retry(
        self,
        operation: Callable[[], Awaitable[Struct]],
    ) -> Struct:
        """Повторные попытки через tenacity (из BaseConnector)."""
        last_error: Exception | None = None

        for attempt in range(1, self._retry_limit + 1):
            try:
                async with self._semaphore:
                    return await operation()

            except GigaChatError as exc:
                last_error = exc
                if attempt >= self._retry_limit:
                    break
                await asyncio.sleep(self._retry_delay)
            except Exception as exc:
                mapped = map_gigachat_error(exc)
                last_error = mapped
                if attempt >= self._retry_limit:
                    break
                await asyncio.sleep(self._retry_delay)

        raise GigaChatError(
            message="GigaChat request failed after all attempts",
            attempts=self._retry_limit,
        ) from last_error
