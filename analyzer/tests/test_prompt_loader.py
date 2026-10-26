from types import SimpleNamespace

from app.agents.gigachat_provider.gigachat_provider import GigaChatProvider
from app.agents.prompt_loader import PromptLoader
from app.schemas.analysis import DialogAnalysisResponse


def test_prompt_catalog_is_loaded_and_rendered_from_resources() -> None:
    loader = PromptLoader()

    system_prompt, user_prompt = loader.render_dialog(
        "Сотрудник: Добрый день",
        "general",
    )

    assert len(loader.criteria_by_block["general"]) == 27
    assert len(loader.criteria_by_block["deposit"]) == 13
    assert system_prompt
    assert "Сотрудник: Добрый день" in user_prompt
    assert "КРИТЕРИИ:" in user_prompt


def test_local_e2e_can_enable_only_selected_criteria() -> None:
    loader = PromptLoader(active_criteria_codes={"GENERAL_01", "GENERAL_02"})

    assert {item.code for item in loader.criteria_by_block["general"]} == {
        "GENERAL_01",
        "GENERAL_02",
    }
    assert len(loader.criteria_by_block["deposit"]) == 13
    _, user_prompt = loader.render_dialog("Сотрудник: Добрый день", "general")
    assert "GENERAL_01" in user_prompt
    assert "GENERAL_02" in user_prompt
    assert "GENERAL_03" not in user_prompt


def test_structured_payload_uses_strict_pydantic_schema() -> None:
    provider = GigaChatProvider.__new__(GigaChatProvider)
    provider._settings = SimpleNamespace(
        gigachat_model="GigaChat-2-Pro",
        gigachat_max_output_tokens=8000,
        gigachat_repetition_penalty=1.0,
        gigachat_temperature=0.1,
        gigachat_top_p=None,
    )

    payload = provider._completion_payload(
        system_prompt="system",
        user_prompt="user",
        response_model=DialogAnalysisResponse,
    )

    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["strict"] is True
    assert payload["response_format"]["schema"] == (
        DialogAnalysisResponse.model_json_schema()
    )
    assert payload["temperature"] == 0.1
    assert "top_p" not in payload
