import pytest

from app.agents.gigachat_provider.factory import create_llm_provider
from app.agents.gigachat_provider.ollama_provider import OllamaProvider
from app.config import Settings


@pytest.mark.asyncio
async def test_factory_selects_local_ollama_provider() -> None:
    settings = Settings(
        LLM_PROVIDER="ollama",
    )

    provider = create_llm_provider(settings)
    try:
        assert isinstance(provider, OllamaProvider)
        assert await provider.count_tokens(["1234567890"]) == 5
    finally:
        await provider.close()
