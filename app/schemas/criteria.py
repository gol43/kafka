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
    severity: Literal["critical", "significant", "minor"] = "minor"
    risk_level: Literal["high", "medium", "low"] | None = None
    quote_required: bool = True
    recommendation: str = Field(min_length=1)

    @model_validator(mode='after')
    def validate_risk_severity(self):
        if self.block == "risk" and self.risk_level is None:
            raise ValueError("risk criterion requires risk_level")
        if self.block != "risk" and self.risk_level is not None:
            raise ValueError("risk_level is allowed only for risk criteria")
        return self
