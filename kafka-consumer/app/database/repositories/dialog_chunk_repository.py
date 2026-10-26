from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import session_scope
from app.database.models import DialogChunk, DialogState


class DialogChunkRepository:
    """Owns every query against Kafka Consumer chunk tables."""

    async def save_chunk(
        self,
        *,
        call_id: str,
        part: int,
        is_last: bool,
        encrypted: bool,
        payload: bytes,
    ) -> None:
        async with session_scope() as session:
            await session.execute(
                insert(DialogChunk)
                .values(
                    call_id=call_id,
                    part=part,
                    is_last=is_last,
                    encrypted=encrypted,
                    payload=payload,
                )
                .on_conflict_do_nothing(index_elements=["call_id", "part"])
            )

            await session.execute(
                insert(DialogState)
                .values(
                    call_id=call_id,
                    status="ready" if is_last else "collecting",
                    last_part=part if is_last else None,
                )
                .on_conflict_do_update(
                    index_elements=["call_id"],
                    set_={
                        "status": "ready" if is_last else DialogState.status,
                        "last_part": part if is_last else DialogState.last_part,
                    },
                )
            )

    async def pop_complete_dialog(self, call_id: str) -> list[DialogChunk]:
        """Lock, read and permanently delete a completed dialog.

        The deletion-before-HTTP behavior is intentional and follows the
        agreed at-most-once handoff contract with Data Cleaner.
        """

        async with session_scope() as session:
            state = await session.scalar(
                select(DialogState)
                .where(DialogState.call_id == call_id)
                .with_for_update()
            )
            if state is None or state.status not in {"ready", "collecting"}:
                return []

            chunks = list(
                (
                    await session.scalars(
                        select(DialogChunk)
                        .where(DialogChunk.call_id == call_id)
                        .order_by(DialogChunk.part)
                    )
                ).all()
            )

            await session.execute(
                delete(DialogChunk).where(DialogChunk.call_id == call_id)
            )
            await session.execute(
                delete(DialogState).where(DialogState.call_id == call_id)
            )

            return chunks
