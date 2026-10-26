import httpx

from app.schemas.analyzer_steps import ExternalAnalyzerResponse


class ExternalAnalyzerAgent:
    """Асинхронно вызывает один внешний анализатор по HTTP."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def analyze(self, payload: dict) -> dict:
        """Отправляет нормализованный диалог и ожидает завершённый результат."""

        response = await self._client.post(
            f"{self._base_url}/internal/v1/analyze",
            json=payload,
        )
        response.raise_for_status()
        result = ExternalAnalyzerResponse.model_validate(response.json())
        if result.status != "completed":
            raise ValueError(f"{self.name} вернул статус {result.status}")
        return result.result

    async def close(self) -> None:
        """Закрывает общий HTTP connection pool."""

        await self._client.aclose()
