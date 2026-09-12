"""HTTP contract tests for meal creation and updates."""

import datetime as dt
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meals import Meal
from app.models.user import User
from app.routers.meals import router
from app.utils.db import get_current_user, get_db


@pytest_asyncio.fixture
async def meal_api(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create an HTTP client backed by the test database and owner identity."""
    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield db

    async def override_current_user() -> User:
        user = await db.scalar(select(User).where(User.user_id == "test-user"))
        assert user is not None
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_post_creates_once_and_duplicate_preserves_original_menu(
    meal_api: AsyncClient, db: AsyncSession
) -> None:
    """POST creates a meal once and does not overwrite an existing unique key."""
    payload = {
        "menu": ["원본 메뉴"],
        "meal_type": "lunch",
        "date": "2026-09-12",
    }

    created = await meal_api.post("/meals/1", json=payload)
    duplicate = await meal_api.post(
        "/meals/1", json={**payload, "menu": ["덮어쓰면 안 되는 메뉴"]}
    )

    assert created.status_code == 201
    assert duplicate.status_code == 409

    meal = await db.scalar(
        select(Meal).where(
            Meal.restaurant_id == 1,
            Meal.date == dt.date(2026, 9, 12),
        )
    )
    assert meal is not None
    assert meal.menu == ["원본 메뉴"]


@pytest.mark.asyncio
async def test_patch_updates_only_the_requested_meal(
    meal_api: AsyncClient,
) -> None:
    """PATCH changes the specified meal and returns its updated representation."""
    created = await meal_api.post(
        "/meals/1",
        json={
            "menu": ["수정 전"],
            "meal_type": "lunch",
            "date": "2026-09-12",
        },
    )
    meal_id = created.json()["data"]["id"]

    updated = await meal_api.patch(
        f"/meals/{meal_id}",
        json={
            "restaurant_id": 1,
            "menu": ["수정 후"],
            "meal_type": "dinner",
            "date": "2026-09-13",
        },
    )

    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["data"] == {
        "id": meal_id,
        "restaurant_id": 1,
        "restaurant_name": "TIP",
        "menu": ["수정 후"],
        "meal_type": "dinner",
        "date": "2026-09-13",
        "registered_at": created.json()["data"]["registered_at"],
        "updated_at": updated.json()["data"]["updated_at"],
    }


@pytest.mark.asyncio
async def test_patch_unique_collision_returns_conflict_and_preserves_original(
    meal_api: AsyncClient, db: AsyncSession
) -> None:
    """PATCH rolls back a date move that collides with another meal."""
    first = await meal_api.post(
        "/meals/1",
        json={
            "menu": ["첫 식단"],
            "meal_type": "lunch",
            "date": "2026-09-12",
        },
    )
    blocker = await meal_api.post(
        "/meals/1",
        json={
            "menu": ["기존 식단"],
            "meal_type": "lunch",
            "date": "2026-09-13",
        },
    )
    meal_id = first.json()["data"]["id"]

    collision = await meal_api.patch(
        f"/meals/{meal_id}",
        json={
            "restaurant_id": 1,
            "menu": ["충돌 메뉴"],
            "meal_type": "lunch",
            "date": "2026-09-13",
        },
    )

    assert first.status_code == 201
    assert blocker.status_code == 201
    assert collision.status_code == 409

    original = await db.get(Meal, meal_id)
    assert original is not None
    assert original.date == dt.date(2026, 9, 12)
    assert original.menu == ["첫 식단"]
