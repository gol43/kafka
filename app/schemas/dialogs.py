from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EmotionVector(BaseModel):
    positive: float = 0.0
    neutral: float = 0.0
    negative: float = 0.0
    positive_a: float = 0.0
    neutral_a: float = 0.0
    negative_a: float = 0.0
    positive_t: float = 0.0
    neutral_t: float = 0.0
    negative_t: float = 0.0


class WordAlignment(BaseModel):
    word: str
    start_ms: int
    end_ms: int


class Utterance(BaseModel):
    sequence_number: int
    speaker_role: Literal["employee", "client", "unknown"]
    speaker_id: int | None = None
    channel: int | None = None
    text: str
    normalized_text: str
    start_ms: int
    end_ms: int
    eou: bool = False
    eou_reason: str | None = None
    main_speaker_confidence: float | None = None
    emotions: EmotionVector | None = None
    word_alignments: list[WordAlignment] = Field(default_factory=list)


class Participant(BaseModel):
    role: Literal["employee", "client", "unknown"]
    name: str | None = None
    phone_number: str | None = None
    employee_id: str | None = None


class CleanedDialog(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    call_id: str = Field(min_length=1, max_length=64)
    manager_id: str
    client_epk: str = Field(min_length=1, max_length=128)
    client_fio: str | None = Field(default=None, min_length=1, max_length=4096)
    client_fio_encrypted: bool = False
    duration_seconds: int = Field(ge=0)
    occurred_at: datetime | None = None
    channel: str | None = None
    participants: list[Participant]
    cleaned_text: str = Field(min_length=1)
    utterances: list[Utterance]
    source_metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_client_fio(self):
        if self.client_fio_encrypted and not self.client_fio:
            raise ValueError("client_fio is required when client_fio_encrypted=true")
        if self.client_fio and not self.client_fio_encrypted and len(self.client_fio) > 256:
            raise ValueError("client_fio must contain at most 256 characters")
        return self

    @field_validator("manager_id")
    @classmethod
    def manager_id_is_normalized(cls, value: str) -> str:
        if not value.isdigit() or len(value) != 8:
            raise ValueError("manager_id must be eight digits")
        return value
