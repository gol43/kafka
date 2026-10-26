import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoService:
    def __init__(self, encoded_key: str | None):
        self._key = base64.urlsafe_b64decode(encoded_key) if encoded_key else None
        if self._key is not None and len(self._key) not in (16, 24, 32):
            raise ValueError("CRYPTO_KEY must be a base64 encoded AES key")

    def decrypt(self, value: bytes) -> bytes:
        if self._key is None:
            raise RuntimeError("Encryption key is not configured")
        return AESGCM(self._key).decrypt(value[:12], value[12:], None)
