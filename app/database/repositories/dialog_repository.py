from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import AnalysisTask, Dialog, DialogReport
from app.exceptions import AnalysisDeadlineExceededError
from app.schemas.dialogs import CleanedDialog
from app.schemas.entities import DialogEntity


class DialogRepository:
    """SQL-операции входящего диалога и его финального отчёта."""

    def __init__(self, ttl_days: int) -> None:
        self._ttl = timedelta(days=ttl_days)

    async def save_cleaned_dialog(
        self,
        payload: CleanedDialog,
        work_date: date,
        required_analyzers: tuple[str, ...],
        *,
        criteria_version: str,
        model_name: str,
        prompt_version: str,
    ) -> bool:
        """Сохраняет только диалоги, которых ещё нет среди готовых отчётов."""
        received_at = datetime.now(UTC)
        occurred_at = payload.occurred_at or received_at
        duration_seconds = payload.duration_seconds

        async with session_scope() as session:
            completed_exists = await session.scalar(
                select(DialogReport.call_id).where(DialogReport.call_id == payload.call_id)
            )
            if completed_exists is not None:
                return False

            result = await session.execute(
                insert(Dialog)
                .values(
                    call_id=payload.call_id,
                    manager_id=payload.manager_id,
                    client_epk=payload.client_epk,
                    client_fio=payload.client_fio or "",
                    client_fio_encrypted=payload.client_fio_encrypted,
                    work_date=work_date,
                    occurred_at=occurred_at,
                    received_at=received_at,
                    duration_seconds=duration_seconds,
                    cleaned_text=payload.cleaned_text,
                    source_payload=payload.model_dump(
                        mode="json",
                        exclude={"cleaned_text"},
                    ),
                    required_analyzers=list(required_analyzers),
                    status="waiting",
                    criteria_version=criteria_version,
                    model_name=model_name,
                    prompt_version=prompt_version,
                    expires_at=received_at + self._ttl,
                )
                .on_conflict_do_nothing(index_elements=["call_id"])
                .returning(Dialog.call_id)
            )
            saved_call_id = result.scalar_one_or_none()
            if saved_call_id is None:
                return False

            await session.execute(
                insert(AnalysisTask)
                .values(
                    call_id=saved_call_id,
                    status="waiting",
                    expires_at=received_at + self._ttl,
                )
                .on_conflict_do_nothing(index_elements=["call_id"])
            )
            return True

    async def get(self, call_id: str) -> DialogEntity | None:
        async with session_scope() as session:
            dialog = await session.get(Dialog, call_id)
            return DialogEntity.model_validate(dialog) if dialog else None

    async def complete_analysis(
        self,
        *,
        call_id: str,
        hygiene_results: list[dict],
        deposit_results: list[dict],
        risk_results: list[dict],
        audio_results: dict,
        factor_results: dict,
        hygiene_score: int,
        deposit_score: int | None,
        score: int,
        deposit_topic: bool,
        critical_violation: bool,
        deviations_count: int,
        risks_count: int,
        report_payload: dict,
    ) -> None:
        """Сохраняет отчёт и удаляет входной диалог вместе с completed task."""
        completed_at = datetime.now(UTC)
        async with session_scope() as session:
            dialog = await session.get(Dialog, call_id, with_for_update=True)
            if dialog is None:
                raise ValueError("Входящий диалог не найден")
            if dialog.status != "processing":
                raise AnalysisDeadlineExceededError(
                    "Диалог уже закрыт без анализа после cutoff"
                )

            statement = insert(DialogReport).values(
                call_id=dialog.call_id,
                manager_id=dialog.manager_id,
                client_epk=dialog.client_epk,
                client_fio=dialog.client_fio,
                client_fio_encrypted=dialog.client_fio_encrypted,
                work_date=dialog.work_date,
                occurred_at=dialog.occurred_at,
                cleaned_text=dialog.cleaned_text,
                source_payload=dialog.source_payload,
                hygiene_results=hygiene_results,
                deposit_results=deposit_results,
                risk_results=risk_results,
                audio_results=audio_results,
                factor_results=factor_results,
                hygiene_score=hygiene_score,
                deposit_score=deposit_score,
                score=score,
                deposit_topic=deposit_topic,
                critical_violation=critical_violation,
                deviations_count=deviations_count,
                risks_count=risks_count,
                report_payload=report_payload,
                criteria_version=dialog.criteria_version,
                prompt_version=dialog.prompt_version,
                model_name=dialog.model_name,
                completed_at=completed_at,
                expires_at=completed_at + self._ttl,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[DialogReport.call_id],
                    set_={
                        "hygiene_results": statement.excluded.hygiene_results,
                        "client_fio": statement.excluded.client_fio,
                        "client_fio_encrypted": statement.excluded.client_fio_encrypted,
                        "deposit_results": statement.excluded.deposit_results,
                        "risk_results": statement.excluded.risk_results,
                        "source_payload": statement.excluded.source_payload,
                        "audio_results": statement.excluded.audio_results,
                        "factor_results": statement.excluded.factor_results,
                        "hygiene_score": statement.excluded.hygiene_score,
                        "deposit_score": statement.excluded.deposit_score,
                        "score": statement.excluded.score,
                        "deposit_topic": statement.excluded.deposit_topic,
                        "critical_violation": statement.excluded.critical_violation,
                        "deviations_count": statement.excluded.deviations_count,
                        "risks_count": statement.excluded.risks_count,
                        "report_payload": statement.excluded.report_payload,
                        "completed_at": statement.excluded.completed_at,
                        "expires_at": statement.excluded.expires_at,
                    },
                )
            )
            await session.delete(dialog)

    async def mark_failed(self, call_id: str, error_code: str) -> None:
        async with session_scope() as session:
            dialog = await session.get(Dialog, call_id, with_for_update=True)
            if dialog and dialog.status == "processing":
                dialog.status = "failed"
                dialog.error_code = error_code

    async def cleanup_expired(self, now: datetime, batch_size: int) -> None:
        await self._delete_expired(Dialog, now, batch_size)
        await self._delete_expired(DialogReport, now, batch_size)

    @staticmethod
    async def _delete_expired(model, now: datetime, batch_size: int) -> None:
        while True:
            async with session_scope() as session:
                ids = select(model.call_id).where(model.expires_at < now).limit(batch_size)
                result = await session.execute(
                    delete(model).where(model.call_id.in_(ids)).returning(model.call_id)
                )
                deleted = len(result.scalars().all())
            if deleted < batch_size:
                return
