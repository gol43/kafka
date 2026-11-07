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

        all_criteria = self._load_criteria()
        if active_criteria_codes:
            known_codes = set()
            for criterion in all_criteria:
                known_codes.add(criterion.code)
            unknown_codes = active_criteria_codes - known_codes
            if unknown_codes:
                raise ValueError(
                    f"Неизвестные ACTIVE_CRITERIA_CODES: {sorted(unknown_codes)}"
                )
            selected_criteria = []
            for criterion in all_criteria:
                is_required_block = criterion.block in {"deposit", "risk"}
                if is_required_block or criterion.code in active_criteria_codes:
                    selected_criteria.append(criterion)
            self.criteria = tuple(selected_criteria)
        else:
            self.criteria = tuple(all_criteria)

        self.criteria_by_code = {}
        for criterion in self.criteria:
            self.criteria_by_code[criterion.code] = criterion

        self.criteria_by_block = {}
        for block in ("hygiene", "deposit", "risk"):
            block_criteria = []
            for criterion in self.criteria:
                if criterion.block == block:
                    block_criteria.append(criterion)
            self.criteria_by_block[block] = tuple(block_criteria)

    def render_dialog(
        self, dialog_text: str, block: str = "hygiene"
    ) -> tuple[str, str]:
        criteria = self.criteria_by_block.get(block)
        if not criteria:
            raise ValueError(f"Для блока {block} не настроены критерии")

        criteria_payload = []
        for criterion in criteria:
            criteria_payload.append(criterion.model_dump(
                exclude={
                    "penalty",
                    "severity",
                    "recommendation",
                },
                mode="json",
            ))

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
            for item in items:
                criteria.append(CriterionDefinition.model_validate(item))

        criteria = tuple(criteria)
        if not criteria:
            raise ValueError("Каталог критериев промпта пуст")

        codes = []
        for criterion in criteria:
            codes.append(criterion.code)
        if len(codes) != len(set(codes)):
            raise ValueError("Каталог критериев содержит повторяющиеся коды")

        return criteria

    def _read_text(self, name: str) -> str:
        text = (self._directory / name).read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"Файл промпта пуст: {name}")
        return text
