from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CriterionDefinition(BaseModel):
    """Один критерий Prompt 4Q, загруженный из YAML при старте."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    title_positive: str = Field(min_length=1)
    title_negative: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rules: str = Field(min_length=1)
    trigger: str = Field(min_length=1)
    positive_definition: str = Field(min_length=1)
    negative_definition: str = Field(min_length=1)
    good_examples: list[str] = Field(default_factory=list)
    bad_examples: list[str] = Field(default_factory=list)
    output_rule: str = Field(min_length=1)
    penalty: int
    block: Literal["hygiene", "deposit", "risk"] = "hygiene"
    severity: Literal[
        "critical",
        "significant",
        "minor",
        "info",
        "high",
        "medium",
        "low",
    ] = "minor"
    quote_required: bool = True
    recommendation: str = Field(min_length=1)

    @model_validator(mode='after')
    def validate_risk_severity(self):
        if self.block == 'risk' and self.severity not in {'high', 'medium', 'low'}:
            raise ValueError("risk can be only - high, medium or low")
        return self
