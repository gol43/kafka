from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import engine, session_scope
from app.database.models import DashboardAggregate, DashboardSnapshot


class DashboardRepository:
    """Пакетно хранит дневную математику и готовые snapshot витрины."""

    def __init__(self, ttl_days: int) -> None:
        self._ttl = timedelta(days=ttl_days)

    @asynccontextmanager
    async def build_lock(self):
        lock_key = 7142026
        async with engine.connect() as connection:
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            try:
                yield bool(acquired)
            finally:
                if acquired:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": lock_key},
                    )

    async def save_aggregates(self, rows: list[dict], now: datetime) -> None:
        if not rows:
            return
        values = []
        for row in rows:
            values.append({**row, "expires_at": now + self._ttl})
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
                        "weekly_metrics": excluded.weekly_metrics,
                        "quarter_score_data": excluded.quarter_score_data,
                        "month_score_data": excluded.month_score_data,
                        "created_at": now,
                        "expires_at": excluded.expires_at,
                    },
                )
            )

    async def delete_manager_history(self, manager_ids: list[str]) -> None:
        if not manager_ids:
            return
        async with session_scope() as session:
            await session.execute(
                delete(DashboardSnapshot).where(
                    DashboardSnapshot.manager_id.in_(manager_ids)
                )
            )
            await session.execute(
                delete(DashboardAggregate).where(
                    DashboardAggregate.manager_id.in_(manager_ids)
                )
            )

    async def aggregates_between(
        self,
        manager_ids: list[str],
        start: date,
        end: date,
    ) -> dict[str, list[tuple[date, dict]]]:
        result = {}
        for manager_id in manager_ids:
            result[manager_id] = []
        if not manager_ids or start > end:
            return result
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        DashboardAggregate.manager_id,
                        DashboardAggregate.aggregate_date,
                        DashboardAggregate.dialogs_count,
                        DashboardAggregate.dialog_score_sum,
                        DashboardAggregate.dialog_score_count,
                        DashboardAggregate.daily_metrics,
                        DashboardAggregate.daily_risks,
                        DashboardAggregate.weekly_metrics,
                        DashboardAggregate.quarter_score_data,
                        DashboardAggregate.month_score_data,
                    )
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
            ).mappings().all()
            for row in rows:
                result[row["manager_id"]].append(
                    (row["aggregate_date"], _aggregate_payload(row))
                )
            return result

    async def latest_snapshots_before(
        self,
        manager_ids: list[str],
        report_date: date,
    ) -> dict[str, dict]:
        if not manager_ids:
            return {}
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        DashboardSnapshot.manager_id,
                        DashboardSnapshot.q_score,
                    )
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
            result = {}
            for manager_id, q_score in rows:
                result[manager_id] = q_score
            return result

    async def latest_aggregates_before(
        self,
        manager_ids: list[str],
        aggregate_date: date,
    ) -> dict[str, dict]:
        if not manager_ids:
            return {}
        async with session_scope() as session:
            rows = (
                await session.execute(
                    select(
                        DashboardAggregate.manager_id,
                        DashboardAggregate.quarter_score_data,
                        DashboardAggregate.month_score_data,
                    )
                    .distinct(DashboardAggregate.manager_id)
                    .where(
                        DashboardAggregate.manager_id.in_(manager_ids),
                        DashboardAggregate.aggregate_date < aggregate_date,
                    )
                    .order_by(
                        DashboardAggregate.manager_id,
                        DashboardAggregate.aggregate_date.desc(),
                    )
                )
            ).all()
            result = {}
            for manager_id, quarter, month in rows:
                result[manager_id] = {
                    "quarter": quarter,
                    "month": month,
                }
            return result

    async def save_snapshots(self, rows: list[dict], now: datetime) -> None:
        if not rows:
            return
        values = []
        for row in rows:
            values.append({**row, "expires_at": now + self._ttl})
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
                        "q_score": excluded.q_score,
                        "risks": excluded.risks,
                        "certain_client_risks": excluded.certain_client_risks,
                        "strengths": excluded.strengths,
                        "improvements": excluded.improvements,
                        "certain_improvement_metrics": excluded.certain_improvement_metrics,
                        "created_at": now,
                        "expires_at": excluded.expires_at,
                    },
                )
            )

    async def latest_snapshot_value(
        self,
        manager_id: str,
        name: str,
    ) -> tuple[date, object] | None:
        columns = {
            "q_score": DashboardSnapshot.q_score,
            "risks": DashboardSnapshot.risks,
            "certain_client_risks": DashboardSnapshot.certain_client_risks,
            "strengths": DashboardSnapshot.strengths,
            "improvements": DashboardSnapshot.improvements,
            "certain_improvement_metrics": DashboardSnapshot.certain_improvement_metrics,
        }
        column = columns.get(name)
        if column is None:
            raise ValueError(f"Неизвестный блок витрины: {name}")

        async with session_scope() as session:
            row = (
                await session.execute(
                    select(
                        DashboardSnapshot.report_date,
                        column,
                    )
                    .where(DashboardSnapshot.manager_id == manager_id)
                    .order_by(DashboardSnapshot.report_date.desc())
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            return row[0], row[1]

    async def latest_report_date(self, manager_id: str) -> date | None:
        async with session_scope() as session:
            return await session.scalar(
                select(DashboardSnapshot.report_date)
                .where(DashboardSnapshot.manager_id == manager_id)
                .order_by(DashboardSnapshot.report_date.desc())
                .limit(1)
            )

    async def compact_history(
        self,
        report_date: date,
        risk_days: int,
        metric_days: int,
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
                .values(daily_metrics={})
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


def _aggregate_payload(row) -> dict:
    return {
        "daily": {
            "dialogsCount": row["dialogs_count"],
            "dialogScoreSum": row["dialog_score_sum"],
            "dialogScoreCount": row["dialog_score_count"],
            "metrics": row["daily_metrics"],
            "risks": row["daily_risks"],
        },
        "week": row["weekly_metrics"],
        "quarter": row["quarter_score_data"],
        "month": row["month_score_data"],
    }
