from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import DashboardAggregate, DashboardSnapshot


class DashboardRepository:
    """Хранит дневную математику и готовые snapshot витрины."""

    def __init__(self, ttl_days: int) -> None:
        self._ttl = timedelta(days=ttl_days)

    async def save_aggregate(
        self,
        manager_id: str,
        aggregate_date: date,
        data: dict,
        now: datetime,
    ) -> None:
        async with session_scope() as session:
            statement = insert(DashboardAggregate).values(
                manager_id=manager_id,
                aggregate_date=aggregate_date,
                data=data,
                expires_at=now + self._ttl,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_dashboard_aggregate",
                    set_={
                        "data": statement.excluded.data,
                        "created_at": now,
                        "expires_at": statement.excluded.expires_at,
                    },
                )
            )

    async def aggregate(
        self,
        manager_id: str,
        aggregate_date: date,
    ) -> dict | None:
        async with session_scope() as session:
            row = await session.scalar(
                select(DashboardAggregate).where(
                    DashboardAggregate.manager_id == manager_id,
                    DashboardAggregate.aggregate_date == aggregate_date,
                )
            )
            return row.data if row else None

    async def aggregates_between(
        self,
        manager_id: str,
        start: date,
        end: date,
    ) -> list[tuple[date, dict]]:
        async with session_scope() as session:
            rows = (
                await session.scalars(
                    select(DashboardAggregate)
                    .where(
                        DashboardAggregate.manager_id == manager_id,
                        DashboardAggregate.aggregate_date >= start,
                        DashboardAggregate.aggregate_date <= end,
                    )
                    .order_by(DashboardAggregate.aggregate_date)
                )
            ).all()
            return [(row.aggregate_date, row.data) for row in rows]

    async def save_snapshot(
        self,
        *,
        manager_id: str,
        report_date: date,
        q_score_block: dict,
        client_risks_block: list,
        client_risk_details: dict,
        strengths_block: list,
        improvements_block: list,
        improvement_details: dict,
        communications_block: list,
        source_call_ids: list,
        now: datetime,
    ) -> None:
        async with session_scope() as session:
            statement = insert(DashboardSnapshot).values(
                manager_id=manager_id,
                report_date=report_date,
                q_score_block=q_score_block,
                client_risks_block=client_risks_block,
                client_risk_details=client_risk_details,
                strengths_block=strengths_block,
                improvements_block=improvements_block,
                improvement_details=improvement_details,
                communications_block=communications_block,
                source_call_ids=source_call_ids,
                expires_at=now + self._ttl,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_dashboard_snapshot",
                    set_={
                        "q_score_block": statement.excluded.q_score_block,
                        "client_risks_block": statement.excluded.client_risks_block,
                        "client_risk_details": statement.excluded.client_risk_details,
                        "strengths_block": statement.excluded.strengths_block,
                        "improvements_block": statement.excluded.improvements_block,
                        "improvement_details": statement.excluded.improvement_details,
                        "communications_block": statement.excluded.communications_block,
                        "source_call_ids": statement.excluded.source_call_ids,
                        "created_at": now,
                        "expires_at": statement.excluded.expires_at,
                    },
                )
            )

    async def snapshot(self, manager_id: str, report_date: date) -> DashboardSnapshot | None:
        async with session_scope() as session:
            return await session.scalar(
                select(DashboardSnapshot).where(
                    DashboardSnapshot.manager_id == manager_id,
                    DashboardSnapshot.report_date == report_date,
                )
            )

    async def cleanup_expired(self, now: datetime) -> None:
        async with session_scope() as session:
            await session.execute(
                delete(DashboardAggregate).where(DashboardAggregate.expires_at < now)
            )
            await session.execute(
                delete(DashboardSnapshot).where(DashboardSnapshot.expires_at < now)
            )
