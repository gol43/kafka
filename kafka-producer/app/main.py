from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status

from app.config import get_settings
from app.producer_service import DialogProducerService
from app.schemas import PublishDialogRequest, PublishDialogResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    producer = DialogProducerService(get_settings())
    await producer.start()
    app.state.producer = producer
    try:
        yield
    finally:
        await producer.close()


app = FastAPI(
    title="E2E Kafka Dialog Producer",
    description="Ручная отправка цельного диалога в тестовый Kafka pipeline.",
    lifespan=lifespan,
)


@app.post(
    "/dialogs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PublishDialogResponse,
)
async def publish_dialog(
    payload: PublishDialogRequest,
    request: Request,
) -> PublishDialogResponse:
    return await request.app.state.producer.publish(payload)


@app.get("/health/ready")
async def readiness() -> dict[str, str]:
    return {"status": "ready"}
