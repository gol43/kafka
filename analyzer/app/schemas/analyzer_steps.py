from pydantic import BaseModel, ConfigDict, Field


class AnalyzerStepResult(BaseModel):
    """Унифицированный результат одного шага анализа диалога."""

    model_config = ConfigDict(extra="forbid")

    analyzer: str
    payload: dict = Field(default_factory=dict)
    q_score: float | None = None
    critical_violation: bool = False
    criteria: list[dict] = Field(default_factory=list)


class ExternalAnalyzerResponse(BaseModel):
    """Контракт ответа внешнего Audio или Factor Analyzer."""

    model_config = ConfigDict(extra="forbid")

    status: str
    result: dict = Field(default_factory=dict)
