from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import get_session_maker
from app.database.models import AnonymizationTask, CallbackDelivery


def utc_now():
    return datetime.now(timezone.utc)


class AnonymizationRepository:
    def __init__(self):
        self.session_maker = get_session_maker()

    async def save_task(self, call_id: str, payload: dict, ttl_days: int) -> bool:
        expires_at = utc_now() + timedelta(days=ttl_days)
        async with self.session_maker() as session:
            statement = insert(AnonymizationTask).values(
                call_id=call_id, payload=payload, expires_at=expires_at
            ).on_conflict_do_nothing(index_elements=[AnonymizationTask.call_id])
            result = await session.execute(statement)
            await session.commit()
            return result.rowcount > 0

    async def claim_task(self):
        now = utc_now()
        async with self.session_maker() as session:
            async with session.begin():
                query = (
                    select(AnonymizationTask)
                    .where(AnonymizationTask.status == "waiting", AnonymizationTask.next_attempt_at <= now)
                    .order_by(AnonymizationTask.created_at)
                    .limit(1).with_for_update(skip_locked=True)
                )
                task = await session.scalar(query)
                if task is None:
                    return None
                task.status = "processing"
                task.claimed_at = now
                await session.flush()
                return task.id, task.call_id, task.payload, task.expires_at

    async def finish_cleaning(self, task_id: str, deliveries: list[dict]) -> None:
        async with self.session_maker() as session:
            async with session.begin():
                task = await session.get(AnonymizationTask, task_id, with_for_update=True)
                if task is None or task.status != "processing":
                    return
                for item in deliveries:
                    session.add(CallbackDelivery(
                        call_id=task.call_id,
                        subscriber_name=item["name"],
                        subscriber_url=item["url"],
                        body=item["body"],
                        expires_at=task.expires_at,
                    ))
                await session.delete(task)

    async def fail_cleaning(self, task_id: str, error: str) -> None:
        async with self.session_maker() as session:
            await session.execute(
                update(AnonymizationTask)
                .where(AnonymizationTask.id == task_id, AnonymizationTask.status == "processing")
                .values(status="failed", last_error=error[:1000], claimed_at=None)
            )
            await session.commit()

    async def claim_delivery(self):
        now = utc_now()
        async with self.session_maker() as session:
            async with session.begin():
                query = (
                    select(CallbackDelivery)
                    .where(CallbackDelivery.status == "waiting", CallbackDelivery.next_attempt_at <= now)
                    .order_by(CallbackDelivery.created_at)
                    .limit(1).with_for_update(skip_locked=True)
                )
                item = await session.scalar(query)
                if item is None:
                    return None
                item.status = "processing"
                item.claimed_at = now
                await session.flush()
                return item.id, item.call_id, item.subscriber_name, item.subscriber_url, item.body, item.attempts

    async def finish_delivery(self, delivery_id: str, error: str | None, max_attempts: int, retry_seconds: int) -> bool:
        """True означает, что попытки исчерпаны и payload удалён."""
        async with self.session_maker() as session:
            async with session.begin():
                item = await session.get(CallbackDelivery, delivery_id, with_for_update=True)
                if item is None:
                    return False
                if error is None:
                    await session.delete(item)
                    return False
                item.attempts += 1
                if item.attempts >= max_attempts:
                    await session.delete(item)
                    return True
                item.status = "waiting"
                item.claimed_at = None
                item.next_attempt_at = utc_now() + timedelta(seconds=retry_seconds)
                item.last_error = error[:1000]
                return False

    async def recover_stale(self, seconds: int) -> None:
        old = utc_now() - timedelta(seconds=seconds)
        async with self.session_maker() as session:
            for model in (AnonymizationTask, CallbackDelivery):
                await session.execute(
                    update(model)
                    .where(model.status == "processing", model.claimed_at < old)
                    .values(status="waiting", claimed_at=None, next_attempt_at=utc_now())
                )
            await session.commit()

    async def cleanup_expired(self) -> None:
        now = utc_now()
        async with self.session_maker() as session:
            await session.execute(delete(CallbackDelivery).where(CallbackDelivery.expires_at <= now))
            await session.execute(delete(AnonymizationTask).where(AnonymizationTask.expires_at <= now))
            await session.commit()
