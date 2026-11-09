from cryptography.fernet import Fernet

from app.config import get_settings


class CryptoService:
    """Сырой текст всегда шифруется до записи в БД."""

    def __init__(self):
        key = get_settings().encryption_key
        if not key:
            raise ValueError("ENCRYPTION_KEY is required")
        self._fernet = Fernet(key.encode("ascii"))

    def encrypt(self, data: str) -> str:
        return self._fernet.encrypt(data.encode("utf-8")).decode("ascii")

    def decrypt(self, data: str) -> str:
        return self._fernet.decrypt(data.encode("ascii")).decode("utf-8")
