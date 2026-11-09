from datetime import datetime

from pydantic import BaseModel, Field


class AnonymizationRequest(BaseModel):
    """Сырой вход. Содержимое реплик пока не фиксируем жёсткой схемой."""

    call_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1)
    manager_id: str | None = Field(default=None, pattern=r"^\d{8}$")
    client_epk: str | None = Field(default=None, max_length=128)
    client_fio: str | None = Field(default=None, max_length=256)
    duration_seconds: int | None = Field(default=None, ge=0)
    occurred_at: datetime | None = None
    channel: str | None = None
    utterances: list[dict] = Field(default_factory=list)
    source_metadata: dict = Field(default_factory=dict)
    callback_url: str | None = Field(default=None, max_length=1000)
    is_encrypted: bool = False


class AnonymizationResponse(BaseModel):
    status: str = "accepted"
    message: str = "Запрос на очистку принят в обработку"
