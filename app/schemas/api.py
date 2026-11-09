from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DialogRunRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    call_id: str = Field(min_length=1)


class AcceptedResponse(BaseModel):
    status: str = "accepted"


class DashboardTestDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    manager_ids: list[str] = Field(min_length=1, max_length=50)
    date_from: date
    date_to: date
    dialogs_per_workday: int = Field(default=5, ge=1, le=100)
    scenario: Literal[
        "mixed",
        "happy_path",
        "no_deposit_topic",
        "client_high_risk",
        "multiple_client_risks",
        "critical_violation",
        "strengths_boundary_80",
        "improvement_boundary_79",
        "no_dialogs",
    ] = "mixed"
    metric_scores: dict[str, int] = Field(default_factory=dict)
    client_epk: str = ""
    client_fio: str = ""

    @field_validator("manager_ids")
    @classmethod
    def validate_manager_ids(cls, values: list[str]) -> list[str]:
        result = []
        for value in values:
            if not value.isdigit() or len(value) > 8:
                raise ValueError("manager_id должен содержать не больше восьми цифр")
            normalized = value.zfill(8)
            if normalized not in result:
                result.append(normalized)
        return result

    @field_validator("metric_scores")
    @classmethod
    def validate_metric_scores(cls, values: dict[str, int]) -> dict[str, int]:
        for code, score in values.items():
            if score not in (0, 1):
                raise ValueError(f"metric_scores.{code} должен быть 0 или 1")
        return values

    @model_validator(mode="after")
    def validate_period(self):
        if self.date_from > self.date_to:
            raise ValueError("date_from не может быть позже date_to")
        if (self.date_to - self.date_from).days >= 183:
            raise ValueError("Тестовый период не может превышать 183 дня")
        return self
