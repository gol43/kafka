import asyncio
import logging

import orjson

from app.config import Settings
from app.database.models import CleanerJob
from app.database.repositories.cleaner_job_repository import CleanerJobRepository
from app.exceptions import InvalidDialogError, UcpUnavailableError
from app.metrics import CLEANER_PROCESSED
from app.schemas.dialogs import CleanedDialog, StructuredDialog
from app.services.crypto import CryptoService
from app.services.dispatcher import CallbackDispatcher
from app.services.text_cleaner import TextCleaner
from app.services.ucp_client import UcpClient

logger = logging.getLogger(__name__)


class CleanerWorker:
    """Claims Cleaner jobs and coordinates the complete cleaning pipeline."""

    def __init__(
        self,
        settings: Settings,
        repository: CleanerJobRepository,
        crypto: CryptoService,
        cleaner: TextCleaner,
        ucp: UcpClient,
        dispatcher: CallbackDispatcher,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._crypto = crypto
        self._cleaner = cleaner
        self._ucp = ucp
        self._dispatcher = dispatcher
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        recovered = False
        logger.info(
            "Cleaner worker started poll=%s",
            self._settings.cleaner_poll_interval_seconds,
        )

        while self._running:
            try:
                if not recovered:
                    await self._repository.recover_processing()
                    recovered = True

                jobs = await self._repository.claim(
                    self._settings.cleaner_worker_batch_size
                )
            except Exception as exc:  # noqa: BLE001
                recovered = False
                logger.error("Cleaner poll failed error=%s", type(exc).__name__)
                await asyncio.sleep(self._settings.cleaner_poll_interval_seconds)
                continue

            if not jobs:
                await asyncio.sleep(self._settings.cleaner_poll_interval_seconds)
                continue

            logger.info("Cleaner jobs claimed count=%s", len(jobs))
            for job in jobs:
                await self._handle(job)

    async def _handle(self, job: CleanerJob) -> None:
        logger.info("Cleaner job started call_id=%s", job.call_id)
        try:
            cleaned_dialog = await self._clean(job)
            self._dispatcher.dispatch(cleaned_dialog.model_dump(mode="json"))
            logger.info("Cleaner callback queued call_id=%s", job.call_id)
            CLEANER_PROCESSED.labels(outcome="completed").inc()
        except Exception as exc:  # noqa: BLE001
            CLEANER_PROCESSED.labels(outcome="dropped").inc()
            logger.error(
                "Cleaner job dropped call_id=%s error=%s",
                job.call_id,
                type(exc).__name__,
            )
        finally:
            await self._repository.delete(job.id)

    async def _clean(self, job: CleanerJob) -> CleanedDialog:
        payload = self._crypto.decrypt(job.payload) if job.encrypted else job.payload
        dialog = StructuredDialog.model_validate(orjson.loads(payload))

        client = next(
            (
                participant
                for participant in dialog.participants
                if participant.role == "client" and participant.phone_number
            ),
            None,
        )
        manager = next(
            (
                participant
                for participant in dialog.participants
                if participant.role == "employee"
            ),
            None,
        )
        if client is None or manager is None or not manager.name:
            raise InvalidDialogError("required participant data is missing")

        ucp_data = await self._ucp.resolve(
            dialog.call_id,
            dialog.manager_id,
            client.phone_number,
        )
        if ucp_data is None:
            raise UcpUnavailableError("UCP did not return mandatory dialog data")

        for utterance in dialog.utterances:
            utterance.text = self._cleaner.clean(utterance.text)
            utterance.normalized_text = self._cleaner.clean(utterance.normalized_text)

        return CleanedDialog(
            call_id=dialog.call_id,
            manager_id=dialog.manager_id,
            manager_name=manager.name,
            client_epk=str(ucp_data["client_epk"]),
            occurred_at=dialog.occurred_at,
            channel=dialog.channel,
            participants=dialog.participants,
            cleaned_text=self._cleaner.clean(dialog.text),
            utterances=dialog.utterances,
            source_metadata={**dialog.source_metadata, "ucp": ucp_data},
        )
