from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CriterionDefinition(BaseModel):
    """Один критерий Prompt 4Q, загруженный из YAML при старте."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    title: str
    description: str
    rules: str
    trigger: str
    positive_definition: str
    negative_definition: str
    good_examples: list[str] = Field(default_factory=list)
    bad_examples: list[str] = Field(default_factory=list)
    output_rule: str
    penalty: int
    critical: bool
    block: Literal["general", "deposit"] = "general"
    severity: Literal["critical", "significant", "minor", "fraud", "info"] = (
        "minor"
    )
    quote_required: bool = True
    recommendation: str = ""
    enabled: bool = True
    prompt_supported: bool = True
    topic_gate: bool = False
