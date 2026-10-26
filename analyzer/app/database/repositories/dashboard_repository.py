from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import (
    ClientMetricSnapshot,
    Dialog,
    DialogMetricResult,
    ManagerDashboardSnapshot,
    ManagerMetricSnapshot,
)


class DashboardRepository:
    """Читает факты анализа и сохраняет готовые payload дашборда."""

    async def completed_dialogs(
        self,
        manager_id: str,
        start: date | None,
        end: date,
    ) -> list[Dialog]:
        query = select(Dialog).where(
            Dialog.manager_id == manager_id,
            Dialog.analysis_status == "completed",
            Dialog.occurred_at < _next_day(end),
        )
        if start is not None:
            query = query.where(Dialog.occurred_at >= _day_start(start))
        query = query.order_by(Dialog.occurred_at.desc())
        async with session_scope() as session:
            return list((await session.scalars(query)).all())

    async def metric_results(
        self,
        manager_id: str,
        start: date,
        end: date,
    ) -> list[DialogMetricResult]:
        async with session_scope() as session:
            return list(
                (
                    await session.scalars(
                        select(DialogMetricResult).where(
                            DialogMetricResult.manager_id == manager_id,
                            DialogMetricResult.included_in_analytics.is_(True),
                            DialogMetricResult.occurred_at >= _day_start(start),
                            DialogMetricResult.occurred_at < _next_day(end),
                        )
                    )
                ).all()
            )

    async def save_dashboard(
        self,
        manager_id: str,
        snapshot_date: date,
        payload: dict,
        client_details: list[dict],
        metric_details: list[dict],
    ) -> None:
        async with session_scope() as session:
            statement = insert(ManagerDashboardSnapshot).values(
                manager_id=manager_id,
                snapshot_date=snapshot_date,
                payload=payload,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_manager_dashboard",
                    set_={"payload": statement.excluded.payload},
                )
            )
            await session.execute(
                delete(ClientMetricSnapshot).where(
                    ClientMetricSnapshot.manager_id == manager_id,
                    ClientMetricSnapshot.snapshot_date == snapshot_date,
                )
            )
            await session.execute(
                delete(ManagerMetricSnapshot).where(
                    ManagerMetricSnapshot.manager_id == manager_id,
                    ManagerMetricSnapshot.snapshot_date == snapshot_date,
                )
            )
            session.add_all(
                ClientMetricSnapshot(
                    manager_id=manager_id,
                    client_epk=item["clientEpk"],
                    metric_code=item["metricCode"],
                    snapshot_date=snapshot_date,
                    payload=item,
                )
                for item in client_details
            )
            session.add_all(
                ManagerMetricSnapshot(
                    manager_id=manager_id,
                    metric_code=item["metricCode"],
                    snapshot_date=snapshot_date,
                    payload=item,
                )
                for item in metric_details
            )

    async def latest_dashboard(self, manager_id: str) -> dict | None:
        async with session_scope() as session:
            row = await session.scalar(
                select(ManagerDashboardSnapshot)
                .where(ManagerDashboardSnapshot.manager_id == manager_id)
                .order_by(ManagerDashboardSnapshot.snapshot_date.desc())
                .limit(1)
            )
            return row.payload if row else None

    async def latest_client_metric(
        self,
        manager_id: str,
        client_epk: str,
        metric_code: str,
    ) -> dict | None:
        async with session_scope() as session:
            row = await session.scalar(
                select(ClientMetricSnapshot)
                .where(
                    ClientMetricSnapshot.manager_id == manager_id,
                    ClientMetricSnapshot.client_epk == client_epk,
                    ClientMetricSnapshot.metric_code == metric_code,
                )
                .order_by(ClientMetricSnapshot.snapshot_date.desc())
                .limit(1)
            )
            return row.payload if row else None

    async def latest_manager_metric(
        self,
        manager_id: str,
        metric_code: str,
    ) -> dict | None:
        async with session_scope() as session:
            row = await session.scalar(
                select(ManagerMetricSnapshot)
                .where(
                    ManagerMetricSnapshot.manager_id == manager_id,
                    ManagerMetricSnapshot.metric_code == metric_code,
                )
                .order_by(ManagerMetricSnapshot.snapshot_date.desc())
                .limit(1)
            )
            return row.payload if row else None


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _next_day(value: date) -> datetime:
    return datetime.combine(value + timedelta(days=1), time.min, tzinfo=UTC)
