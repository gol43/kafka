import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api.router import router
from app.config import get_settings
from app.database.connection import get_database_engine
from app.database.repository import AnonymizationRepository
from app.services.cleaner_worker import AnonymizationWorker
from app.services.crypto_service import CryptoService
from app.services.service import DataCleanerService


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.subscribers()
    crypto = CryptoService()
    repository = AnonymizationRepository()
    app.state.data_cleaner_service = DataCleanerService(repository, crypto)
    worker = AnonymizationWorker(repository, crypto)
    task = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await worker.http_client.aclose()
        await get_database_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(router, prefix=settings.app_api_prefix)
    return app


app = create_app()
