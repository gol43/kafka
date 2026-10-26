import hashlib

from fastapi import FastAPI, Query

app = FastAPI(title="E2E UCP Mock")


@app.get("/internal/v1/client")
async def resolve_client(
    call_id: str,
    manager_id: str,
    phone: str = Query(min_length=1),
) -> dict[str, str]:
    """Всегда возвращает стабильный тестовый EPK для валидного номера."""

    digest = hashlib.sha256(phone.encode("utf-8")).hexdigest()[:16]
    return {
        "client_epk": f"E2E-{digest}",
        "call_id": call_id,
        "manager_id": manager_id,
    }


@app.get("/health/ready")
async def readiness() -> dict[str, str]:
    return {"status": "ready"}
