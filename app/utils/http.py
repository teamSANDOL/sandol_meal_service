from httpx import AsyncClient


async def get_async_client() -> AsyncClient:
    async with AsyncClient() as client:
        yield client
