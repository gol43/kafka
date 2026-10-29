from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import distinct, select
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

    async def for_work_date(
        self,
        manager_id: str,
        work_date: date,
    ) -> list[DialogReportEntity]:
        async with session_scope() as session:
            rows = (
                await session.scalars(
                    select(DialogReport)
                    .where(
                        DialogReport.manager_id == manager_id,
                        DialogReport.work_date == work_date,
                    )
                    .order_by(DialogReport.occurred_at)
                )
            ).all()
            return [DialogReportEntity.model_validate(row) for row in rows]

    async def manager_ids_through(self, report_date: date) -> set[str]:
        """Возвращает только менеджеров, у которых уже есть готовые отчёты."""

        async with session_scope() as session:
            values = await session.scalars(
                select(distinct(DialogReport.manager_id)).where(
                    DialogReport.work_date <= report_date,
                )
            )
            return set(values.all())

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
