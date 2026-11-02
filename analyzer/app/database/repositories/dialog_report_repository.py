from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import DialogReport
from app.schemas.entities import DialogReportEntity


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
    ) -> dict[str, list[DialogReportEntity]]:
        result = {manager_id: [] for manager_id in manager_ids}
        if not manager_ids:
            return result
        async with session_scope() as session:
            rows = (
                await session.scalars(
                    select(DialogReport)
                    .where(
                        DialogReport.manager_id.in_(manager_ids),
                        DialogReport.work_date == work_date,
                    )
                    .order_by(DialogReport.occurred_at)
                )
            ).all()
        for row in rows:
            result[row.manager_id].append(DialogReportEntity.model_validate(row))
        return result

    async def latest_for_managers(
        self,
        manager_ids: list[str],
        report_date: date,
        limit: int,
    ) -> dict[str, list[DialogReportEntity]]:
        result = {manager_id: [] for manager_id in manager_ids}
        if not manager_ids:
            return result
        ranked = (
            select(
                DialogReport.call_id.label("call_id"),
                func.row_number()
                .over(
                    partition_by=DialogReport.manager_id,
                    order_by=DialogReport.occurred_at.desc(),
                )
                .label("row_number"),
            )
            .where(
                DialogReport.manager_id.in_(manager_ids),
                DialogReport.work_date <= report_date,
            )
            .subquery()
        )
        async with session_scope() as session:
            rows = (
                await session.scalars(
                    select(DialogReport)
                    .join(ranked, ranked.c.call_id == DialogReport.call_id)
                    .where(ranked.c.row_number <= limit)
                    .order_by(DialogReport.manager_id, DialogReport.occurred_at.desc())
                )
            ).all()
        for row in rows:
            result[row.manager_id].append(DialogReportEntity.model_validate(row))
        return result

    async def upsert_test_report(self, values: dict) -> None:
        """Кладёт готовый fixture-отчёт без обхода dashboard-математики."""

        async with session_scope() as session:
            statement = insert(DialogReport).values(**values)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[DialogReport.call_id],
                    set_={
                        key: getattr(statement.excluded, key)
                        for key in values
                        if key != "call_id"
                    },
                )
            )

    async def list_for_manager(
        self,
        *,
        manager_id: str,
        report_date: date,
        limit: int,
        client_epk: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[DialogReportEntity]:
        query = select(DialogReport).where(
            DialogReport.manager_id == manager_id,
            DialogReport.work_date <= report_date,
        )
        if client_epk:
            query = query.where(DialogReport.client_epk == client_epk)
        if date_from:
            query = query.where(DialogReport.occurred_at >= _day_start(date_from))
        if date_to:
            query = query.where(DialogReport.occurred_at < _next_day(date_to))
        query = query.order_by(DialogReport.occurred_at.desc()).limit(limit)

        async with session_scope() as session:
            rows = (await session.scalars(query)).all()
            return [DialogReportEntity.model_validate(row) for row in rows]


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _next_day(value: date) -> datetime:
    return _day_start(value + timedelta(days=1))
