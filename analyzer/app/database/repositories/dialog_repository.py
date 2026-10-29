from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import Dialog, DialogReport
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
        if duration_seconds is None:
            duration_seconds = max(
                (item.end_ms for item in payload.utterances),
                default=0,
            ) // 1000

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
                    work_date=work_date,
                    occurred_at=occurred_at,
                    received_at=received_at,
                    duration_seconds=duration_seconds,
                    cleaned_text=payload.cleaned_text,
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
            return result.scalar_one_or_none() is not None

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
        general_score: float,
        deposit_score: float | None,
        score: float,
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

            statement = insert(DialogReport).values(
                call_id=dialog.call_id,
                manager_id=dialog.manager_id,
                client_epk=dialog.client_epk,
                work_date=dialog.work_date,
                occurred_at=dialog.occurred_at,
                cleaned_text=dialog.cleaned_text,
                hygiene_results=hygiene_results,
                deposit_results=deposit_results,
                risk_results=risk_results,
                audio_results=audio_results,
                factor_results=factor_results,
                general_score=general_score,
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
                        "deposit_results": statement.excluded.deposit_results,
                        "risk_results": statement.excluded.risk_results,
                        "audio_results": statement.excluded.audio_results,
                        "factor_results": statement.excluded.factor_results,
                        "general_score": statement.excluded.general_score,
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
            if dialog:
                dialog.status = "failed"
                dialog.error_code = error_code

    async def pending_before_cutoff(self, work_date: date, cutoff: datetime) -> int:
        async with session_scope() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(Dialog)
                    .where(
                        Dialog.work_date == work_date,
                        Dialog.received_at < cutoff,
                        Dialog.status.in_(("waiting", "processing")),
                    )
                )
                or 0
            )

    async def cleanup_expired(self, now: datetime) -> None:
        async with session_scope() as session:
            await session.execute(delete(Dialog).where(Dialog.expires_at < now))
            await session.execute(
                delete(DialogReport).where(DialogReport.expires_at < now)
            )
