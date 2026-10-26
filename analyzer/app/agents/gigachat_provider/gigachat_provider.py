import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.agents.gigachat_provider.base import BaseGigaChatProvider, ResponseModel
from app.agents.gigachat_provider.exceptions import GigaChatError
from app.config import Settings
from app.metrics import GIGACHAT_ACTIVE, GIGACHAT_REQUESTS

Result = TypeVar("Result")


class GigaChatProvider(BaseGigaChatProvider):
    """Асинхронный REST-клиент GigaChat с общим ограничением конкурентности."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.gigachat_max_concurrency)
        self._client = httpx.AsyncClient(
            timeout=settings.gigachat_timeout_seconds,
            verify=settings.gigachat_verify_ssl,
            cert=self._client_certificate(),
        )

        self._access_token_value: str | None = None
        self._access_token_expires_at = 0.0
        self._access_token_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def chat_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
    ) -> ResponseModel:
        async def operation() -> ResponseModel:
            payload = self._completion_payload(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
            )
            data = await self._post_once("/chat/completions", payload)
            content = data["choices"][0]["message"]["content"]
            return response_model.model_validate_json(content)

        return await self._with_attempts(operation)

    async def count_tokens(self, values: list[str]) -> int:
        async def operation() -> int:
            payload = {
                "model": self._settings.gigachat_model,
                "input": values,
            }
            data = await self._post_once("/tokens/count", payload)
            return sum(int(item.get("tokens", 0)) for item in data)

        return await self._with_attempts(operation)

    def _completion_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> dict:
        payload: dict = {
            "model": self._settings.gigachat_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "max_tokens": self._settings.gigachat_max_output_tokens,
            "repetition_penalty": self._settings.gigachat_repetition_penalty,
            "response_format": {
                "type": "json_schema",
                "schema": response_model.model_json_schema(),
                "strict": True,
            },
        }

        if self._settings.gigachat_temperature is not None:
            payload["temperature"] = self._settings.gigachat_temperature
        if self._settings.gigachat_top_p is not None:
            payload["top_p"] = self._settings.gigachat_top_p

        return payload

    async def _post_once(self, path: str, payload: dict) -> dict:
        operation = path.strip("/").replace("/", "_")

        async with self._semaphore:
            GIGACHAT_ACTIVE.inc()
            try:
                token = await self._access_token()
                response = await self._client.post(
                    f"{self._settings.gigachat_base_url.rstrip('/')}{path}",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                if response.status_code == 401:
                    self._access_token_value = None
                response.raise_for_status()

                GIGACHAT_REQUESTS.labels(
                    operation=operation,
                    outcome="success",
                ).inc()
                return response.json()
            except Exception:
                GIGACHAT_REQUESTS.labels(
                    operation=operation,
                    outcome="error",
                ).inc()
                raise
            finally:
                GIGACHAT_ACTIVE.dec()

    async def _access_token(self) -> str:
        if self._token_is_valid():
            return self._access_token_value  # type: ignore[return-value]

        async with self._access_token_lock:
            if self._token_is_valid():
                return self._access_token_value  # type: ignore[return-value]

            response = await self._client.post(
                self._settings.gigachat_auth_url,
                headers={
                    "Authorization": f"Basic {self._settings.gigachat_credentials}",
                    "RqUID": str(uuid.uuid4()),
                },
                data={"scope": self._settings.gigachat_scope},
            )
            response.raise_for_status()
            data = response.json()

            self._access_token_value = data["access_token"]
            expires_at = float(data["expires_at"])
            self._access_token_expires_at = (
                expires_at / 1000 if expires_at > 10_000_000_000 else expires_at
            )
            return self._access_token_value

    def _token_is_valid(self) -> bool:
        return bool(
            self._access_token_value
            and time.time() < self._access_token_expires_at - 30
        )

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
            "GigaChat request failed after all attempts",
            attempts=self._settings.gigachat_max_attempts,
        ) from last_error

    def _client_certificate(self) -> tuple[str, str] | None:
        cert_file = self._settings.gigachat_cert_file
        key_file = self._settings.gigachat_key_file
        if not cert_file and not key_file:
            return None
        if not cert_file or not key_file:
            raise ValueError(
                "GIGACHAT_CERT_FILE and GIGACHAT_KEY_FILE must be configured together"
            )
        return cert_file, key_file
