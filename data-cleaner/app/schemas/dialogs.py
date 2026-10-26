import base64
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CleanerRequest(BaseModel):
    call_id: str
    encrypted: bool
    payload: str

    def decoded_payload(self) -> bytes:
        return base64.b64decode(self.payload, validate=True)


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


class StructuredDialog(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    contract_version: str = "1.0"
    call_id: str
    manager_id: str
    occurred_at: datetime | None = None
    channel: str | None = None
    participants: list[Participant]
    text: str = Field(min_length=1)
    utterances: list[Utterance]
    source_metadata: dict = Field(default_factory=dict)

    @field_validator("manager_id")
    @classmethod
    def validate_manager(cls, value: str) -> str:
        if not value.isdigit() or len(value) > 8:
            raise ValueError("Invalid manager_id")
        return value.zfill(8)


class CleanedDialog(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    contract_version: str = "1.0"
    cleaner_version: str = "1.0"
    call_id: str
    manager_id: str
    manager_name: str = Field(min_length=1)
    client_epk: str = Field(min_length=1)
    occurred_at: datetime | None = None
    channel: str | None = None
    participants: list[Participant]
    cleaned_text: str = Field(min_length=1)
    utterances: list[Utterance]
    source_metadata: dict = Field(default_factory=dict)
    encrypted: Literal[False] = False
