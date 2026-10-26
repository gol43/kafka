from datetime import UTC, date, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import Dialog, DialogMetricResult
from app.schemas.dialogs import CleanedDialog
from app.schemas.entities import DialogEntity


class DialogRepository:
    """Все SQL-операции с диалогом и результатом его анализа."""

    async def save_cleaned_dialog(
        self,
        payload: CleanedDialog,
        work_date: date,
        required_analyzers: tuple[str, ...],
        *,
        criteria_version: str,
        model_name: str,
        prompt_version: str,
    ) -> None:
        """Сохраняет диалог и реплики одним объектом без дублирования строк."""

        dialog_data = [
            {
                "sequence_number": utterance.sequence_number,
                "speaker_role": utterance.speaker_role,
                "speaker_id": utterance.speaker_id,
                "channel": utterance.channel,
                "text": utterance.normalized_text,
                "start_ms": utterance.start_ms,
                "end_ms": utterance.end_ms,
                "eou": utterance.eou,
                "eou_reason": utterance.eou_reason,
                "main_speaker_confidence": utterance.main_speaker_confidence,
                "emotions": (
                    utterance.emotions.model_dump(mode="json")
                    if utterance.emotions
                    else None
                ),
                "word_alignments": [
                    item.model_dump(mode="json") for item in utterance.word_alignments
                ],
            }
            for utterance in payload.utterances
        ]
        client_fio = payload.client_fio or next(
            (
                participant.name
                for participant in payload.participants
                if participant.role == "client" and participant.name
            ),
            "",
        )
        duration_seconds = payload.duration_seconds
        if duration_seconds is None:
            duration_seconds = max(
                (item.end_ms for item in payload.utterances),
                default=0,
            ) // 1000

        async with session_scope() as session:
            await session.execute(
                insert(Dialog)
                .values(
                    call_id=payload.call_id,
                    manager_id=payload.manager_id,
                    manager_name=payload.manager_name,
                    client_epk=payload.client_epk,
                    client_fio=client_fio,
                    work_date=work_date,
                    occurred_at=payload.occurred_at,
                    channel=payload.channel,
                    duration_seconds=duration_seconds,
                    cleaned_text=payload.cleaned_text,
                    dialog_data=dialog_data,
                    required_analyzers=list(required_analyzers),
                    analysis_status="waiting",
                    criteria_version=criteria_version,
                    model_name=model_name,
                    prompt_version=prompt_version,
                )
                .on_conflict_do_nothing(index_elements=["call_id"])
            )

    async def get(self, call_id: str) -> DialogEntity | None:
        """Возвращает диалог по UUID звонка."""

        async with session_scope() as session:
            dialog = await session.get(Dialog, call_id)
            return DialogEntity.model_validate(dialog) if dialog is not None else None

    async def mark_processing(self, call_id: str) -> None:
        """Фиксирует начало полной цепочки анализа диалога."""

        async with session_scope() as session:
            dialog = await session.get(Dialog, call_id, with_for_update=True)
            if dialog is None:
                raise ValueError("Диалог не найден")
            dialog.analysis_status = "processing"
            dialog.error_code = None

    async def complete_analysis(
        self,
        *,
        call_id: str,
        analysis_results: dict,
        q_score: float | None,
        critical_violation: bool,
        criteria: list[dict],
        dialog_report: dict,
        general_score: float | None,
        deposit_topic: bool,
        deposit_score: float | None,
        deviations_count: int,
    ) -> None:
        """Атомарно сохраняет полный результат всех обязательных анализаторов."""

        async with session_scope() as session:
            dialog = await session.get(Dialog, call_id, with_for_update=True)
            if dialog is None:
                raise ValueError("Диалог не найден")

            dialog.analysis_results = analysis_results
            dialog.q_score = q_score
            dialog.general_score = general_score
            dialog.deposit_topic = deposit_topic
            dialog.deposit_score = deposit_score
            dialog.deviations_count = deviations_count
            dialog.dialog_report = dialog_report
            dialog.critical_violation = critical_violation
            dialog.analysis_status = "completed"
            dialog.completed_at = datetime.now(UTC)

            await session.execute(
                delete(DialogMetricResult).where(
                    DialogMetricResult.call_id == call_id
                )
            )
            occurred_at = dialog.occurred_at or dialog.completed_at
            session.add_all(
                DialogMetricResult(
                    call_id=call_id,
                    manager_id=dialog.manager_id,
                    client_epk=dialog.client_epk,
                    metric_code=item["code"],
                    metric_title=item["title"],
                    metric_block=item["block"],
                    score=item["score"],
                    severity=item["severity"],
                    penalty=item["penalty"],
                    quote=item["quote"],
                    recommendation=item["recommendation"],
                    included_in_analytics=item["included_in_analytics"],
                    occurred_at=occurred_at,
                )
                for item in criteria
            )

    async def get_completed(self, call_id: str) -> DialogEntity | None:
        """Возвращает только полностью завершённый анализ диалога."""

        async with session_scope() as session:
            dialog = await session.scalar(
                select(Dialog).where(
                    Dialog.call_id == call_id,
                    Dialog.analysis_status == "completed",
                )
            )
            return DialogEntity.model_validate(dialog) if dialog is not None else None

    async def mark_failed(self, call_id: str, error_code: str) -> None:
        """Сохраняет техническую причину неуспешного анализа."""

        async with session_scope() as session:
            dialog = await session.get(Dialog, call_id, with_for_update=True)
            if dialog is not None:
                dialog.analysis_status = "failed"
                dialog.error_code = error_code
