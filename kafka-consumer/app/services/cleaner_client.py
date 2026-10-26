import base64

import httpx

from app.schemas.dialogs import CleanerRequest, StructuredDialog
from app.services.crypto import CryptoService


class CleanerClient:
    def __init__(
        self,
        base_url: str,
        timeout: float,
        encrypt: bool,
        crypto: CryptoService,
    ):
        self._url = f"{base_url.rstrip('/')}/internal/v1/dialogs"
        self._client = httpx.AsyncClient(timeout=timeout)
        self._encrypt = encrypt
        self._crypto = crypto

    async def close(self) -> None:
        await self._client.aclose()

    async def submit(self, dialog: StructuredDialog) -> bool:
        raw = dialog.model_dump_json().encode()
        payload = self._crypto.encrypt(raw) if self._encrypt else raw
        request = CleanerRequest(
            call_id=dialog.call_id,
            encrypted=self._encrypt,
            payload=base64.b64encode(payload).decode(),
        )
        try:
            response = await self._client.post(self._url, json=request.model_dump())
            return response.status_code == 202
        except httpx.HTTPError:
            return False
