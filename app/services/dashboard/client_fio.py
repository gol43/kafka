from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings


class ClientFioCodec:
    """Готовит ФИО к хранению и расшифровывает его для dashboard/API."""

    def __init__(self, settings: Settings) -> None:
        self.encrypt_at_rest = settings.encrypt_client_fio_at_rest
        self.cipher = None
        if settings.client_fio_encryption_key:
            self.cipher = Fernet(settings.client_fio_encryption_key.encode("ascii"))
        if self.encrypt_at_rest and self.cipher is None:
            raise ValueError(
                "CLIENT_FIO_ENCRYPTION_KEY is required when FIO encryption is enabled"
            )

    def for_storage(self, fio: str | None, encrypted: bool) -> tuple[str, bool]:
        if not fio:
            return "", False
        if encrypted:
            plain = self.for_api(fio, True)
            if len(plain) > 256:
                raise ValueError("client_fio must contain at most 256 characters")
        if encrypted == self.encrypt_at_rest:
            return fio, encrypted
        if self.cipher is None:
            raise ValueError("CLIENT_FIO_ENCRYPTION_KEY is required to convert FIO")
        if encrypted:
            return self._decrypt(fio), False
        return self.cipher.encrypt(fio.encode("utf-8")).decode("ascii"), True

    def for_api(self, fio: str | None, encrypted: bool) -> str:
        if not fio:
            return ""
        if not encrypted:
            return fio
        if self.cipher is None:
            raise ValueError("CLIENT_FIO_ENCRYPTION_KEY is required to read encrypted FIO")
        return self._decrypt(fio)

    def _decrypt(self, token: str) -> str:
        try:
            return self.cipher.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise ValueError("Cannot decrypt client_fio") from exc
