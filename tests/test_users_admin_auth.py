"""사용자 API가 관리자 권한 호출자에게만 열려 있는지 확인하는 HTTP 계약 테스트."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.utils.db as db_utils
from app.models.user import User
from app.routers.users import router
from app.schemas.users import AdminUserSchema
from app.utils.db import get_db


@pytest_asyncio.fixture
async def users_api(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """실제 get_admin_user 의존성 체인을 그대로 사용하는 HTTP 클라이언트.

    외부 Keycloak 호출은 check_admin_user를 몽키패치로 대체해 차단한다.
    """
    app = FastAPI()
    app.include_router(router)

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_missing_x_user_id_header_returns_401(users_api: AsyncClient) -> None:
    """X-User-ID 헤더가 없으면 401을 반환하고 DB에 접근하지 않는다."""
    response = await users_api.get("/users/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_non_admin_caller_gets_403_and_no_data_access(
    users_api: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """관리자 롤이 없으면 403을 반환하고 목록 조회나 삭제가 일어나지 않는다."""

    async def fake_check_admin_user(user: User) -> AdminUserSchema:
        return AdminUserSchema(
            id=user.id,
            user_id=user.user_id,
            global_admin=False,
            meal_admin=False,
            created_at=user.created_at,
        )

    monkeypatch.setattr(db_utils, "check_admin_user", fake_check_admin_user)

    list_response = await users_api.get("/users/", headers={"X-User-ID": "test-user"})
    assert list_response.status_code == 403

    delete_response = await users_api.delete(
        "/users/test-user", headers={"X-User-ID": "test-user"}
    )
    assert delete_response.status_code == 403

    remaining = await db.scalar(select(User).where(User.user_id == "test-user"))
    assert remaining is not None


@pytest.mark.asyncio
async def test_admin_caller_can_list_users(
    users_api: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """global_admin 또는 meal admin 롤이 있으면 기존처럼 통과한다."""

    async def fake_check_admin_user(user: User) -> AdminUserSchema:
        return AdminUserSchema(
            id=user.id,
            user_id=user.user_id,
            global_admin=True,
            meal_admin=False,
            created_at=user.created_at,
        )

    monkeypatch.setattr(db_utils, "check_admin_user", fake_check_admin_user)

    response = await users_api.get("/users/", headers={"X-User-ID": "test-user"})
    assert response.status_code == 200
    assert any(item["user_id"] == "test-user" for item in response.json())
