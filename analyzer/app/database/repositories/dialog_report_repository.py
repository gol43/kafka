from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import DialogReport
from app.schemas.entities import DashboardDialogEntity, DialogReportEntity


class DialogReportRepository:
    """Чтение только готовых анализов диалогов."""

    async def get(self, call_id: str) -> DialogReportEntity | None:
        async with session_scope() as session:
            row = await session.get(DialogReport, call_id)
            return DialogReportEntity.model_validate(row) if row else None

    async def for_work_date_many(
        self,
        manager_ids: list[str],
        work_date: date,
    ) -> dict[str, list[DashboardDialogEntity]]:
        result = _empty_manager_result(manager_ids)
        if not manager_ids:
            return result
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        DialogReport.call_id,
                        DialogReport.manager_id,
                        DialogReport.client_epk,
                        DialogReport.client_fio,
                        DialogReport.occurred_at,
                        DialogReport.score,
                        DialogReport.hygiene_results,
                        DialogReport.deposit_results,
                        DialogReport.risk_results,
                    )
                    .where(
                        DialogReport.manager_id.in_(manager_ids),
                        DialogReport.work_date == work_date,
                    )
                    .order_by(DialogReport.occurred_at)
                )
            ).mappings().all()
            for row in rows:
                entity = DashboardDialogEntity.model_validate(row)
                result[entity.manager_id].append(entity)
            return result

    async def upsert_test_report(self, values: dict) -> None:
        """Кладёт готовый fixture-отчёт без обхода dashboard-математики."""
        async with session_scope() as session:
            statement = insert(DialogReport).values(**values)
            update_values = {}
            for key in values:
                if key != "call_id":
                    update_values[key] = getattr(statement.excluded, key)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[DialogReport.call_id],
                    set_=update_values,
                )
            )

    async def delete_test_reports(self, manager_ids: list[str]) -> None:
        if not manager_ids:
            return
        async with session_scope() as session:
            await session.execute(
                delete(DialogReport).where(
                    DialogReport.manager_id.in_(manager_ids),
                    DialogReport.model_name == "dashboard-test-fixture",
                )
            )

    async def list_completed_dialogs(
        self,
        *,
        manager_id: str,
        work_date: date,
        score: str | None = None,
        client_epk: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[dict]:
        query = select(
            DialogReport.call_id,
            DialogReport.client_epk,
            DialogReport.occurred_at,
            DialogReport.score,
        ).where(
            DialogReport.manager_id == manager_id,
            DialogReport.work_date <= work_date,
        )
        if score == "low":
            query = query.where(DialogReport.score < 41)
        elif score == "medium":
            query = query.where(
                DialogReport.score >= 41,
                DialogReport.score < 80,
            )
        elif score == "high":
            query = query.where(DialogReport.score >= 80)
        if client_epk:
            query = query.where(DialogReport.client_epk == client_epk)
        if date_from:
            query = query.where(DialogReport.occurred_at >= _day_start(date_from))
        if date_to:
            query = query.where(DialogReport.occurred_at < _next_day(date_to))

        query = query.order_by(DialogReport.occurred_at.desc()).limit(limit + 1).offset(offset)

        async with session_scope() as session:
            return list((await session.execute(query)).mappings().all())


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _next_day(value: date) -> datetime:
    return _day_start(value + timedelta(days=1))


def _empty_manager_result(manager_ids: list[str]) -> dict[str, list]:
    result = {}
    for manager_id in manager_ids:
        result[manager_id] = []
    return result
