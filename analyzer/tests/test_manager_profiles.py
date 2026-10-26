import pytest

from app.config import Settings


def test_manager_sets_define_exact_analyzer_chain() -> None:
    settings = Settings(
        ANALYZED_MANAGER_IDS="1,2",
        PROMPT_ANALYZER_MANAGER_IDS="1,2",
        AUDIO_ANALYZER_MANAGER_IDS="2",
        AUDIO_ANALYZER_URL="http://audio:8080",
    )

    assert settings.analyzers_for("00000001") == ("prompt",)
    assert settings.analyzers_for("00000002") == ("prompt", "audio")
    assert settings.analyzers_for("00000003") is None


def test_enabled_manager_must_have_analyzer() -> None:
    with pytest.raises(ValueError, match="не назначен ни один анализатор"):
        Settings(
            ANALYZED_MANAGER_IDS="1",
        )
