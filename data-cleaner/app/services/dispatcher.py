import asyncio
import logging

import httpx

from app.metrics import CLEANER_CALLBACKS

logger = logging.getLogger(__name__)


class CallbackDispatcher:
    def __init__(
        self,
        urls: list[str],
        timeout: float,
        concurrency: int,
        queue_size: int,
    ):
        self._urls = urls
        self._client = httpx.AsyncClient(timeout=timeout)
        self._queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue(
            maxsize=queue_size
        )
        self._workers = [
            asyncio.create_task(self._run(), name=f"callback-{index}")
            for index in range(concurrency)
        ]

    async def close(self) -> None:
        await self._queue.join()
        for _ in self._workers:
            await self._queue.put(None)
        await asyncio.gather(*self._workers, return_exceptions=True)
        await self._client.aclose()

    def dispatch(self, payload: dict) -> None:
        for url in self._urls:
            try:
                self._queue.put_nowait((url, payload))
            except asyncio.QueueFull:
                CLEANER_CALLBACKS.labels(outcome="queue_full").inc()
                logger.warning(
                    "Cleaner callback dropped because queue is full",
                    extra={"callback_url": url},
                )

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return
                await self._send(*item)
            finally:
                self._queue.task_done()

    async def _send(self, url: str, payload: dict) -> None:
        try:
            response = await self._client.post(url, json=payload)
            if response.status_code >= 400:
                CLEANER_CALLBACKS.labels(outcome="rejected").inc()
                logger.warning(
                    "Cleaner callback rejected",
                    extra={"callback_url": url, "status_code": response.status_code},
                )
            else:
                CLEANER_CALLBACKS.labels(outcome="accepted").inc()
        except httpx.HTTPError:
            CLEANER_CALLBACKS.labels(outcome="network_error").inc()
            logger.warning("Cleaner callback failed", extra={"callback_url": url})
