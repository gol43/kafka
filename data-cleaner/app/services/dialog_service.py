import orjson

from app.database.repositories.cleaner_job_repository import CleanerJobRepository
from app.schemas.dialogs import CleanerRequest, StructuredDialog


class DialogService:
    """Validates and persists dialogs accepted from Kafka Consumer."""

    def __init__(self, repository: CleanerJobRepository) -> None:
        self._repository = repository

    async def accept(self, request: CleanerRequest) -> None:
        payload = request.decoded_payload()

        if not request.encrypted:
            dialog = StructuredDialog.model_validate(orjson.loads(payload))
            if dialog.call_id != request.call_id:
                raise ValueError("call_id does not match payload")

        await self._repository.enqueue(
            call_id=request.call_id,
            encrypted=request.encrypted,
            payload=payload,
        )
