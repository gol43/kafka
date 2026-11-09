from gigachat.exceptions import ResponseError as GigaChatResponseError


class GigaChatException(Exception):
    """Базовое исключение GigaChat."""


class GigaChatModelNotAvailable(GigaChatException):
    """Модель недоступна."""


class GigaChatTooManyRequests(GigaChatException):
    """Превышен лимит запросов."""


class GigaChatError(RuntimeError):
    """Ошибка после исчерпания всех попыток запроса GigaChat."""

    def __init__(self, message: str, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class GigaChatRateLimitError(GigaChatError):
    """GigaChat отклонил запрос из-за превышения квоты сертификата."""


class GigaChatResponseError(GigaChatError):
    """Ответ GigaChat не соответствует запрошенной схеме."""


def map_gigachat_error(exc: Exception) -> GigaChatError:
    """Маппит исключения langchain-gigachat на наши ошибки."""
    if isinstance(exc, GigaChatResponseError):
        status = getattr(exc, "status_code", None)
        if status == 429:
            return GigaChatRateLimitError(str(exc), attempts=1)
        return GigaChatResponseError(str(exc), attempts=1)

    if isinstance(exc, (GigaChatException, GigaChatError)):
        return exc

    return GigaChatError(str(exc), attempts=1)