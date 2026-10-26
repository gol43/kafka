from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class BaseGigaChatProvider(ABC):
    @abstractmethod
    async def chat_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
    ) -> ResponseModel:
        raise NotImplementedError

    @abstractmethod
    async def count_tokens(self, values: list[str]) -> int:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError
