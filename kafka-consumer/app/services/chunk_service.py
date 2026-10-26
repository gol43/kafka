import logging

import orjson

from app.config import Settings
from app.database.models import DialogChunk
from app.database.repositories.dialog_chunk_repository import DialogChunkRepository
from app.metrics import DIALOG_DISPATCHES
from app.schemas.dialogs import DialogChunkPayload
from app.services.assembler import assemble_dialog
from app.services.cleaner_client import CleanerClient
from app.services.crypto import CryptoService

logger = logging.getLogger(__name__)


class ChunkService:
    """Coordinates persistence, assembly and the at-most-once Cleaner handoff."""

    def __init__(
        self,
        settings: Settings,
        repository: DialogChunkRepository,
        cleaner: CleanerClient,
        crypto: CryptoService,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._cleaner = cleaner
        self._crypto = crypto

    async def handle(self, chunk: DialogChunkPayload) -> None:
        await self._repository.save_chunk(
            call_id=chunk.call_id,
            part=chunk.part,
            is_last=chunk.is_last,
            encrypted=self._settings.chunk_storage_encrypted,
            payload=self._encode(chunk),
        )

        if chunk.is_last:
            await self._dispatch(chunk.call_id)

    async def _dispatch(self, call_id: str) -> None:
        rows = await self._repository.pop_complete_dialog(call_id)
        if not rows:
            return

        chunks = [self._decode(row) for row in rows]
        try:
            dialog = assemble_dialog(chunks)
        except ValueError:
            DIALOG_DISPATCHES.labels(outcome="invalid").inc()
            logger.warning(
                "Invalid dialog assembly; chunks were dropped",
                extra={"call_id": call_id},
            )
            return

        accepted = await self._cleaner.submit(dialog)
        outcome = "accepted" if accepted else "rejected"
        DIALOG_DISPATCHES.labels(outcome=outcome).inc()

        if not accepted:
            logger.warning(
                "Data Cleaner did not accept dialog; dialog was dropped",
                extra={"call_id": call_id},
            )

    def _encode(self, chunk: DialogChunkPayload) -> bytes:
        raw_payload = orjson.dumps(chunk.model_dump(mode="json"))
        if not self._settings.chunk_storage_encrypted:
            return raw_payload
        return self._crypto.encrypt(raw_payload)

    def _decode(self, row: DialogChunk) -> DialogChunkPayload:
        raw_payload = row.payload
        if row.encrypted:
            raw_payload = self._crypto.decrypt(raw_payload)
        return DialogChunkPayload.model_validate(orjson.loads(raw_payload))
