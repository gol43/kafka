from pydantic import BaseModel, ConfigDict, Field


class CriterionResult(BaseModel):
    """Структурированный результат одного обязательного критерия качества."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1)
    score: int = Field(ge=0, le=1)
    quote: str | None = None


class DialogAnalysisResponse(BaseModel):
    """Строгий контракт ответа GigaChat для одного диалога."""

    model_config = ConfigDict(extra="forbid")

    results: list[CriterionResult] = Field(min_length=1)


class AggregatedRecommendation(BaseModel):
    """Текстовая часть агрегированного отчёта.

    Оценок здесь намеренно нет: приложение само рассчитывает все числа из
    завершённых отчётов предыдущего уровня.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str = Field(min_length=1)
