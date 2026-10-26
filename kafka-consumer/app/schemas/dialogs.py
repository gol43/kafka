from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class DialogChunkPayload(BaseModel):
    call_id: str
    part: int = Field(ge=0)
    is_last: bool
    occurred_at: datetime | None = None
    channel: str | None = None
    manager_id: str
    participants: list[Participant]
    utterances: list[Utterance]
    backend_info: dict[str, str] | None = None
    technical_metadata: dict = Field(default_factory=dict)

    @field_validator("manager_id")
    @classmethod
    def normalize_manager_id(cls, value: str) -> str:
        if not value.isdigit() or len(value) > 8:
            raise ValueError("manager_id must contain at most eight digits")
        return value.zfill(8)


class StructuredDialog(BaseModel):
    contract_version: str = "1.0"
    call_id: str
    manager_id: str
    occurred_at: datetime | None = None
    channel: str | None = None
    participants: list[Participant]
    text: str
    utterances: list[Utterance]
    source_metadata: dict = Field(default_factory=dict)


class CleanerRequest(BaseModel):
    call_id: str
    encrypted: bool
    payload: str
