import json
from pathlib import Path

import yaml

from app.schemas.criteria import CriterionDefinition


class PromptLoader:
    """Один раз при старте загружает и валидирует все prompt-ресурсы."""

    def __init__(
        self,
        prompts_directory: Path | None = None,
        active_criteria_codes: set[str] | None = None,
    ) -> None:
        self._directory = prompts_directory or Path(__file__).parent / "prompts"

        self._dialog_system = self._read_text("dialog_system.md")
        self._dialog_user = self._read_text("dialog_user.md")
        self.positive_templates = tuple(
            yaml.safe_load(
                (self._directory / "positive_templates.yaml").read_text(
                    encoding="utf-8"
                )
            )
        )
        if not self.positive_templates:
            raise ValueError("Список положительных шаблонов пуст")
        all_criteria = self._apply_metadata(self._load_criteria())
        if active_criteria_codes:
            known_codes = {criterion.code for criterion in all_criteria}
            unknown_codes = active_criteria_codes - known_codes
            if unknown_codes:
                raise ValueError(
                    f"Неизвестные ACTIVE_CRITERIA_CODES: {sorted(unknown_codes)}"
                )
            self.criteria = tuple(
                criterion
                for criterion in all_criteria
                if criterion.enabled
                and criterion.prompt_supported
                and (
                    criterion.block == "deposit"
                    or criterion.code in active_criteria_codes
                )
            )
        else:
            self.criteria = tuple(
                item for item in all_criteria if item.enabled and item.prompt_supported
            )
        self.criteria_by_code = {
            criterion.code: criterion for criterion in self.criteria
        }
        self.criteria_by_block = {
            block: tuple(item for item in self.criteria if item.block == block)
            for block in ("general", "deposit")
        }

    def render_dialog(self, dialog_text: str, block: str = "general") -> tuple[str, str]:
        criteria = self.criteria_by_block.get(block)
        if not criteria:
            raise ValueError(f"Для блока {block} не настроены критерии")
        criteria_payload = [
            criterion.model_dump(
                exclude={
                    "penalty",
                    "critical",
                    "severity",
                    "recommendation",
                    "enabled",
                    "prompt_supported",
                    "topic_gate",
                },
                mode="json",
            )
            for criterion in criteria
        ]
        user_prompt = self._dialog_user.format(
            block=block,
            criteria_json=json.dumps(criteria_payload, ensure_ascii=False),
            dialog_text=dialog_text,
        )
        return self._dialog_system, user_prompt

    def _load_criteria(self) -> tuple[CriterionDefinition, ...]:
        criteria_directory = self._directory / "criteria"
        criteria = []
        for path in sorted(criteria_directory.rglob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            items = raw if isinstance(raw, list) else [raw]
            criteria.extend(CriterionDefinition.model_validate(item) for item in items)
        criteria = tuple(criteria)
        if not criteria:
            raise ValueError("Каталог критериев промпта пуст")

        codes = [criterion.code for criterion in criteria]
        if len(codes) != len(set(codes)):
            raise ValueError("Каталог критериев содержит повторяющиеся коды")
        return criteria

    def _read_text(self, name: str) -> str:
        text = (self._directory / name).read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"Файл промпта пуст: {name}")
        return text

    def _apply_metadata(
        self,
        criteria: tuple[CriterionDefinition, ...],
    ) -> tuple[CriterionDefinition, ...]:
        path = self._directory / "metric_metadata.yaml"
        if not path.exists():
            return criteria
        metadata = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return tuple(
            item.model_copy(update=metadata.get(item.code, {}))
            for item in criteria
        )
