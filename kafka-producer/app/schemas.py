from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class PublishDialogRequest(BaseModel):
    """Удобный HTTP-контракт тестового телефонного разговора."""

    call_id: str = Field(default_factory=lambda: str(uuid4()))
    manager_id: str = "00000001"
    manager_name: str = "Тестовый менеджер"
    client_name: str = "Тестовый клиент"
    client_phone: str = "+79990000000"
    direction: Literal["outgoing", "incoming"] = "outgoing"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    dialog_text: str = Field(
        min_length=1,
        examples=[
            (
                "Сотрудник: Здравствуйте, я персональный менеджер.\n"
                "Клиент: Добрый день. Подскажите условия вклада.\n"
                "Сотрудник: Конечно, сначала уточню желаемый срок."
            )
        ],
    )
    chunk_max_chars: int = Field(default=300, ge=20, le=5000)

    @field_validator("manager_id")
    @classmethod
    def normalize_manager_id(cls, value: str) -> str:
        if not value.isdigit() or len(value) > 8:
            raise ValueError("manager_id должен содержать не больше восьми цифр")
        return value.zfill(8)


class PublishDialogResponse(BaseModel):
    call_id: str
    topic: str
    chunks_sent: int
