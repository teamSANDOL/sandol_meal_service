"""이 모듈은 HTTP 비동기 클라이언트를 생성하는 유틸리티 함수를 제공합니다."""

from httpx import AsyncClient
from typing import AsyncGenerator

async def get_async_client() -> AsyncGenerator[AsyncClient, None]:
    """비동기 HTTP 클라이언트를 생성하고 반환합니다.

    이 함수는 httpx.AsyncClient를 사용하여 비동기 HTTP 클라이언트를 생성합니다.
    클라이언트는 비동기 컨텍스트 매니저를 통해 생성되며, 사용 후 자동으로 정리됩니다.

    Returns:
        AsyncGenerator[AsyncClient, None]: 비동기 HTTP 클라이언트 인스턴스를 생성하는 비동기 제너레이터
    """
    async with AsyncClient() as client:
        yield client
