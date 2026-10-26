class GigaChatError(RuntimeError):
    """Ошибка после исчерпания всех попыток запроса GigaChat."""

    def __init__(self, message: str, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class GigaChatRateLimitError(GigaChatError):
    """GigaChat отклонил запрос из-за превышения квоты сертификата."""


class GigaChatResponseError(GigaChatError):
    """Ответ GigaChat не соответствует запрошенной схеме."""
