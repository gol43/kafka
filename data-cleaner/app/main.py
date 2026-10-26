import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from app.api.dialogs import router as dialogs_router
from app.api.health import router as health_router
from app.config import get_settings
from app.database.repositories.cleaner_job_repository import CleanerJobRepository
from app.services.crypto import CryptoService
from app.services.dialog_service import DialogService
from app.services.dispatcher import CallbackDispatcher
from app.services.text_cleaner import TextCleaner
from app.services.ucp_client import UcpClient
from app.services.worker import CleanerWorker

settings = get_settings()
logging.basicConfig(level=settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    repository = CleanerJobRepository()
    crypto = CryptoService(settings.crypto_key)
    text_cleaner = TextCleaner(Path(__file__).parent / "dictionaries" / "roots.yaml")
    ucp_client = UcpClient(
        settings.ucp_base_url,
        settings.ucp_timeout_seconds,
    )
    dispatcher = CallbackDispatcher(
        urls=[str(url) for url in settings.cleaner_callback_urls],
        timeout=settings.cleaner_callback_timeout_seconds,
        concurrency=settings.cleaner_callback_concurrency,
        queue_size=settings.cleaner_callback_queue_size,
    )

    app.state.dialog_service = DialogService(repository)
    worker = CleanerWorker(
        settings=settings,
        repository=repository,
        crypto=crypto,
        cleaner=text_cleaner,
        ucp=ucp_client,
        dispatcher=dispatcher,
    )
    worker_task = asyncio.create_task(worker.run(), name="cleaner-worker")

    try:
        yield
    finally:
        await worker.stop()
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
        await dispatcher.close()
        await ucp_client.close()


app = FastAPI(title="Quality Data Cleaner", lifespan=lifespan)
app.include_router(dialogs_router)
app.include_router(health_router)
app.mount("/metrics", make_asgi_app())
