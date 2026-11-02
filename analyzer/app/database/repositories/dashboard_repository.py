from datetime import date, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import DashboardAggregate, DashboardSnapshot


class DashboardRepository:
    """Пакетно хранит дневную математику и готовые snapshot витрины."""

    def __init__(self, ttl_days: int) -> None:
        self._ttl = timedelta(days=ttl_days)

    async def save_aggregates(self, rows: list[dict], now: datetime) -> None:
        if not rows:
            return
        values = [{**row, "expires_at": now + self._ttl} for row in rows]
        async with session_scope() as session:
            statement = insert(DashboardAggregate).values(values)
            excluded = statement.excluded
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_dashboard_aggregate",
                    set_={
                        "manager_role": excluded.manager_role,
                        "dialogs_count": excluded.dialogs_count,
                        "dialog_score_sum": excluded.dialog_score_sum,
                        "dialog_score_count": excluded.dialog_score_count,
                        "daily_metrics": excluded.daily_metrics,
                        "daily_risks": excluded.daily_risks,
                        "rolling_30_metrics": excluded.rolling_30_metrics,
                        "weekly_metrics": excluded.weekly_metrics,
                        "quarter_score_data": excluded.quarter_score_data,
                        "month_score_data": excluded.month_score_data,
                        "created_at": now,
                        "expires_at": excluded.expires_at,
                    },
                )
            )

    async def aggregates_between(
        self,
        manager_ids: list[str],
        start: date,
        end: date,
    ) -> dict[str, list[tuple[date, dict]]]:
        result = {manager_id: [] for manager_id in manager_ids}
        if not manager_ids or start > end:
            return result
        async with session_scope() as session:
            rows = (
                await session.scalars(
                    select(DashboardAggregate)
                    .where(
                        DashboardAggregate.manager_id.in_(manager_ids),
                        DashboardAggregate.aggregate_date >= start,
                        DashboardAggregate.aggregate_date <= end,
                    )
                    .order_by(
                        DashboardAggregate.manager_id,
                        DashboardAggregate.aggregate_date,
                    )
                )
            ).all()
        for row in rows:
            result[row.manager_id].append((row.aggregate_date, _aggregate_payload(row)))
        return result

    async def latest_snapshots_before(
        self,
        manager_ids: list[str],
        report_date: date,
    ) -> dict[str, DashboardSnapshot]:
        if not manager_ids:
            return {}
        async with session_scope() as session:
            rows = (
                await session.scalars(
                    select(DashboardSnapshot)
                    .distinct(DashboardSnapshot.manager_id)
                    .where(
                        DashboardSnapshot.manager_id.in_(manager_ids),
                        DashboardSnapshot.report_date < report_date,
                    )
                    .order_by(
                        DashboardSnapshot.manager_id,
                        DashboardSnapshot.report_date.desc(),
                    )
                )
            ).all()
        return {row.manager_id: row for row in rows}

    async def save_snapshots(self, rows: list[dict], now: datetime) -> None:
        if not rows:
            return
        values = [{**row, "expires_at": now + self._ttl} for row in rows]
        async with session_scope() as session:
            statement = insert(DashboardSnapshot).values(values)
            excluded = statement.excluded
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_dashboard_snapshot",
                    set_={
                        "manager_role": excluded.manager_role,
                        "source_date": excluded.source_date,
                        "carried_forward": excluded.carried_forward,
                        "q_score_block": excluded.q_score_block,
                        "client_risks_block": excluded.client_risks_block,
                        "client_risk_details": excluded.client_risk_details,
                        "strengths_block": excluded.strengths_block,
                        "improvements_block": excluded.improvements_block,
                        "improvement_details": excluded.improvement_details,
                        "communications_block": excluded.communications_block,
                        "source_call_ids": excluded.source_call_ids,
                        "created_at": now,
                        "expires_at": excluded.expires_at,
                    },
                )
            )

    async def snapshot(
        self,
        manager_id: str,
        report_date: date,
    ) -> DashboardSnapshot | None:
        async with session_scope() as session:
            return await session.scalar(
                select(DashboardSnapshot).where(
                    DashboardSnapshot.manager_id == manager_id,
                    DashboardSnapshot.report_date == report_date,
                )
            )

    async def compact_history(
        self,
        report_date: date,
        risk_days: int,
        metric_days: int,
        weekly_points: int,
    ) -> None:
        """Убирает тяжёлые JSON-детали после окончания их расчётного окна."""

        async with session_scope() as session:
            await session.execute(
                update(DashboardAggregate)
                .where(
                    DashboardAggregate.aggregate_date
                    < report_date - timedelta(days=risk_days - 1),
                    DashboardAggregate.daily_risks != [],
                )
                .values(daily_risks=[])
            )
            await session.execute(
                update(DashboardAggregate)
                .where(
                    DashboardAggregate.aggregate_date
                    < report_date - timedelta(days=metric_days - 1),
                    DashboardAggregate.daily_metrics != {},
                )
                .values(daily_metrics={}, rolling_30_metrics={})
            )
            await session.execute(
                update(DashboardAggregate)
                .where(
                    DashboardAggregate.aggregate_date
                    < report_date - timedelta(days=weekly_points * 7 + 7),
                    DashboardAggregate.weekly_metrics.is_not(None),
                )
                .values(weekly_metrics=None)
            )

    async def cleanup_expired(self, now: datetime, batch_size: int) -> None:
        await self._delete_expired(DashboardAggregate, now, batch_size)
        await self._delete_expired(DashboardSnapshot, now, batch_size)

    @staticmethod
    async def _delete_expired(model, now: datetime, batch_size: int) -> None:
        while True:
            async with session_scope() as session:
                ids = select(model.id).where(model.expires_at < now).limit(batch_size)
                result = await session.execute(
                    delete(model).where(model.id.in_(ids)).returning(model.id)
                )
                deleted = len(result.scalars().all())
            if deleted < batch_size:
                return


def _aggregate_payload(row: DashboardAggregate) -> dict:
    return {
        "managerRole": row.manager_role,
        "daily": {
            "dialogsCount": row.dialogs_count,
            "dialogScoreSum": row.dialog_score_sum,
            "dialogScoreCount": row.dialog_score_count,
            "metrics": row.daily_metrics,
            "risks": row.daily_risks,
        },
        "rolling30": {"metrics": row.rolling_30_metrics},
        "week": row.weekly_metrics or {"completed": False},
        "quarter": row.quarter_score_data,
        "month": row.month_score_data,
    }
