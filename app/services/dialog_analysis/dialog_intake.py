from datetime import UTC, datetime
import logging

from app.config import Settings
from app.database.repositories.dialog_repository import DialogRepository
from app.schemas.dialogs import CleanedDialog
from app.services.dashboard.client_fio import ClientFioCodec
from app.services.dialog_analysis.calendar_policy import resolve_work_date

logger = logging.getLogger(__name__)


class DialogIntakeService:
    """Решает, нужно ли принимать очищенный диалог в Analyzer."""

    def __init__(
        self,
        settings: Settings,
        repository: DialogRepository,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._client_fio = ClientFioCodec(settings)

    async def accept(self, payload: CleanedDialog) -> str:
        """Отбрасывает нерабочее время и менеджеров вне ENV-списка."""
        received_at = datetime.now(UTC)
        stored_fio, encrypted = self._client_fio.for_storage(
            payload.client_fio, payload.client_fio_encrypted
        )
        payload = payload.model_copy(update={
            "client_fio": stored_fio,
            "client_fio_encrypted": encrypted,
        })
        duration_seconds = payload.duration_seconds

        if duration_seconds < self._settings.min_dialog_duration_seconds:
            logger.info("Dialog too short call_id=%s", payload.call_id)
            return "duration_filtered"

        work_date = (
            resolve_work_date(received_at)
            if self._settings.calendar_filter_enabled
            else (payload.occurred_at or received_at).astimezone(UTC).date()
        )
        if work_date is None:
            logger.info("Dialog skipped by calendar call_id=%s", payload.call_id)
            return "calendar_filtered"

        required_analyzers = self._settings.analyzers_for(payload.manager_id)
        if required_analyzers is None:
            logger.info("Dialog manager skipped call_id=%s", payload.call_id)
            return "manager_filtered"
        if not required_analyzers:
            raise ValueError("Для менеджера не назначен ни один анализатор")

        saved = await self._repository.save_cleaned_dialog(
            payload,
            work_date,
            required_analyzers,
            criteria_version=self._settings.criteria_version,
            model_name=self._settings.selected_llm_model,
            prompt_version=self._settings.prompt_version,
        )
        if not saved:
            logger.info("Dialog duplicate ignored call_id=%s", payload.call_id)
            return "duplicate"

        logger.info("Dialog saved call_id=%s", payload.call_id)
        logger.info("Dialog task created call_id=%s", payload.call_id)
        return "accepted"
