import httpx


class UcpClient:
    def __init__(self, base_url: str, timeout: float):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def resolve(
        self, call_id: str, manager_id: str, client_phone: str
    ) -> dict | None:
        try:
            response = await self._client.get(
                "/internal/v1/client",
                params={
                    "call_id": call_id,
                    "manager_id": manager_id,
                    "phone": client_phone,
                },
            )
            if response.status_code != 200:
                return None
            data = response.json()
            if not data.get("client_epk"):
                return None
            return data
        except httpx.HTTPError:
            return None
