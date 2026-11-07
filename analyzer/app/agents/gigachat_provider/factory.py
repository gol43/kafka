from app.agents.gigachat_provider.base import BaseGigaChatProvider
from app.agents.gigachat_provider.gigachat_provider import GigaChatProvider
from app.config import Settings


def create_llm_provider(settings: Settings) -> BaseGigaChatProvider:
    """Создаёт единственный поддерживаемый клиент GigaChat."""
    return GigaChatProvider(settings)
