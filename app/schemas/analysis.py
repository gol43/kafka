from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model


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


def create_block_response_model(
    block: str,
    codes: tuple[str, ...],
) -> type[BaseModel]:
    code_literal = Literal.__getitem__(codes)
    criterion_model = create_model(
        f"{block.title()}CriterionResult",
        __config__=ConfigDict(extra="forbid", str_strip_whitespace=True),
        code=(code_literal, ...),
        score=(int, Field(ge=0, le=1)),
        quote=(str | None, None),
    )
    return create_model(
        f"{block.title()}AnalysisResponse",
        __config__=ConfigDict(extra="forbid"),
        results=(
            list[criterion_model],
            Field(min_length=len(codes), max_length=len(codes)),
        ),
    )
