from app.agents.gigachat_provider.base import BaseGigaChatProvider
from app.agents.gigachat_provider.gigachat_provider import GigaChatProvider
from app.agents.gigachat_provider.ollama_provider import OllamaProvider
from app.config import Settings


def create_llm_provider(settings: Settings) -> BaseGigaChatProvider:
    """Создаёт выбранный через `LLM_PROVIDER` клиент модели."""

    if settings.llm_provider == "ollama":
        return OllamaProvider(settings)
    return GigaChatProvider(settings)
