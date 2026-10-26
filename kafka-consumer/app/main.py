import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from app.api.health import router as health_router
from app.config import get_settings
from app.database.repositories.dialog_chunk_repository import DialogChunkRepository
from app.services.chunk_service import ChunkService
from app.services.cleaner_client import CleanerClient
from app.services.consumer import DialogConsumer
from app.services.crypto import CryptoService

settings = get_settings()
logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    crypto = CryptoService(settings.crypto_key)
    cleaner = CleanerClient(
        base_url=settings.cleaner_base_url,
        timeout=settings.cleaner_timeout_seconds,
        encrypt=settings.cleaner_request_encrypted,
        crypto=crypto,
    )
    repository = DialogChunkRepository()
    chunk_service = ChunkService(settings, repository, cleaner, crypto)
    consumer = DialogConsumer(settings, chunk_service)

    app.state.consumer = consumer
    consumer_task = asyncio.create_task(consumer.run(), name="kafka-consumer")

    try:
        yield
    finally:
        await consumer.stop()
        consumer_task.cancel()
        await asyncio.gather(consumer_task, return_exceptions=True)
        await cleaner.close()


app = FastAPI(title="Quality Kafka Consumer", lifespan=lifespan)
app.include_router(health_router)
app.mount("/metrics", make_asgi_app())
