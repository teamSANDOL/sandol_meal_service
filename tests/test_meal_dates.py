"""Tests for date identity and upsert behavior."""

import datetime as dt

import pytest
from fastapi import HTTPException
from fastapi_pagination import Params
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models.meals import Meal, MealType
from app.routers.meals import latest_meal_by_restaurant, latest_meals_by_restaurant
from app.schemas.meals import MealRegister
from app.utils.meals import apply_date_filter, update_meal_transaction, upsert_meal


@pytest.mark.asyncio
async def test_upsert_replaces_menu_for_same_date(db) -> None:
    """The same restaurant/type/date is replaced instead of duplicated."""
    lunch = await db.scalar(select(MealType).where(MealType.name == "lunch"))
    assert lunch is not None
    meal, created = await upsert_meal(
        db,
        restaurant_id=1,
        meal_type_id=lunch.id,
        menu=["첫 메뉴"],
        date=dt.date(2026, 9, 11),
    )
    await db.commit()
    replacement, replaced_created = await upsert_meal(
        db,
        restaurant_id=1,
        meal_type_id=lunch.id,
        menu=["수정 메뉴"],
        date=dt.date(2026, 9, 11),
    )
    await db.commit()
    assert created is True
    assert replaced_created is False
    assert replacement.id == meal.id
    assert replacement.menu == ["수정 메뉴"]


@pytest.mark.asyncio
async def test_date_filter_is_inclusive(db) -> None:
    """Both boundaries are included in a date range."""
    lunch = await db.scalar(select(MealType).where(MealType.name == "lunch"))
    assert lunch is not None
    for day in (dt.date(2026, 9, 10), dt.date(2026, 9, 11), dt.date(2026, 9, 12)):
        await upsert_meal(
            db,
            restaurant_id=1,
            meal_type_id=lunch.id,
            menu=[day.isoformat()],
            date=day,
        )
    query = await apply_date_filter(select(Meal), "2026-09-10", "2026-09-11")
    meals = (await db.execute(query)).scalars().all()
    assert {meal.date for meal in meals} == {
        dt.date(2026, 9, 10),
        dt.date(2026, 9, 11),
    }


@pytest.mark.asyncio
async def test_date_filter_normalizes_reversed_boundaries(db) -> None:
    """A reversed range still applies both inclusive boundaries."""
    lunch = await db.scalar(select(MealType).where(MealType.name == "lunch"))
    assert lunch is not None
    for day in (dt.date(2026, 9, 10), dt.date(2026, 9, 11), dt.date(2026, 9, 12)):
        await upsert_meal(
            db,
            restaurant_id=1,
            meal_type_id=lunch.id,
            menu=[day.isoformat()],
            date=day,
        )

    query = await apply_date_filter(select(Meal), "2026-09-11", "2026-09-10")
    meals = (await db.execute(query)).scalars().all()

    assert {meal.date for meal in meals} == {
        dt.date(2026, 9, 10),
        dt.date(2026, 9, 11),
    }


@pytest.mark.asyncio
async def test_invalid_date_filter_reports_iso_8601_date_format() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await apply_date_filter(select(Meal), "09/10/2026", None)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == (
        "날짜 형식이 올바르지 않습니다. (YYYY-MM-DD 등 ISO 8601 날짜 형식)"
    )


@pytest.mark.asyncio
async def test_database_unique_key_rejects_duplicate_rows(db) -> None:
    """The database constraint remains the final concurrency guard."""
    lunch = await db.scalar(select(MealType).where(MealType.name == "lunch"))
    assert lunch is not None
    db.add_all(
        [
            Meal(
                restaurant_id=1,
                meal_type_id=lunch.id,
                menu=["a"],
                date=dt.date(2026, 9, 11),
            ),
            Meal(
                restaurant_id=1,
                meal_type_id=lunch.id,
                menu=["b"],
                date=dt.date(2026, 9, 11),
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        await db.commit()


def test_register_schema_requires_date() -> None:
    """Registration without a service date is rejected during validation."""
    with pytest.raises(ValidationError):
        MealRegister.model_validate(
            {
                "meal_type": "lunch",
                "menu": ["김치찌개"],
            }
        )


@pytest.mark.asyncio
async def test_update_date_collision_returns_conflict(db) -> None:
    """Moving a meal onto an occupied date returns HTTP 409."""
    lunch = await db.scalar(select(MealType).where(MealType.name == "lunch"))
    assert lunch is not None
    source, _ = await upsert_meal(
        db,
        restaurant_id=1,
        meal_type_id=lunch.id,
        menu=["원본"],
        date=dt.date(2026, 9, 10),
    )
    await upsert_meal(
        db,
        restaurant_id=1,
        meal_type_id=lunch.id,
        menu=["기존 식단"],
        date=dt.date(2026, 9, 11),
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await update_meal_transaction(
            db,
            source,
            restaurant_id=1,
            meal_type_id=lunch.id,
            menu=["충돌"],
            date=dt.date(2026, 9, 11),
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_latest_uses_reference_date_and_excludes_future(db) -> None:
    """Latest picks the closest meal on or before the requested date."""
    lunch = await db.scalar(select(MealType).where(MealType.name == "lunch"))
    assert lunch is not None
    for day in (
        dt.date(2026, 9, 9),
        dt.date(2026, 9, 10),
        dt.date(2026, 9, 12),
    ):
        await upsert_meal(
            db,
            restaurant_id=1,
            meal_type_id=lunch.id,
            menu=[day.isoformat()],
            date=day,
        )
    await db.commit()

    page = await latest_meals_by_restaurant(
        db=db,
        params=Params(page=1, size=50),
        restaurant_name=None,
        meal_type=None,
        date=dt.date(2026, 9, 11),
    )

    assert len(page.items) == 1
    assert page.items[0].date == dt.date(2026, 9, 10)


@pytest.mark.asyncio
async def test_latest_endpoints_prefer_later_updated_at_for_same_date(db) -> None:
    """Both latest endpoints prefer the most recently updated legacy duplicate."""
    lunch = await db.scalar(select(MealType).where(MealType.name == "lunch"))
    assert lunch is not None

    # Production prevents these duplicates with a unique constraint. Recreate the
    # isolated test table without it to protect the legacy-data tie-breaker.
    await db.execute(text("DROP TABLE meal"))
    await db.execute(
        text(
            """
            CREATE TABLE meal (
                id BIGINT NOT NULL PRIMARY KEY,
                restaurant_id BIGINT NOT NULL,
                menu JSON NOT NULL,
                date DATE NOT NULL,
                registered_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                meal_type_id BIGINT NOT NULL
            )
            """
        )
    )
    earlier_updated = Meal(
        id=1,
        restaurant_id=1,
        meal_type_id=lunch.id,
        menu=["updated last"],
        date=dt.date(2026, 9, 11),
        registered_at=dt.datetime(2026, 9, 11, 12, tzinfo=dt.UTC),
        updated_at=dt.datetime(2026, 9, 11, 16, tzinfo=dt.UTC),
    )
    later_registered = Meal(
        id=2,
        restaurant_id=1,
        meal_type_id=lunch.id,
        menu=["registered last"],
        date=dt.date(2026, 9, 11),
        registered_at=dt.datetime(2026, 9, 11, 15, tzinfo=dt.UTC),
        updated_at=dt.datetime(2026, 9, 11, 14, tzinfo=dt.UTC),
    )
    db.add_all([earlier_updated, later_registered])
    await db.commit()

    global_page = await latest_meals_by_restaurant(
        db=db,
        params=Params(page=1, size=50),
        restaurant_name=None,
        meal_type=None,
        date=dt.date(2026, 9, 11),
    )
    restaurant_page = await latest_meal_by_restaurant(
        restaurant_id=1,
        db=db,
        params=Params(page=1, size=50),
        date=dt.date(2026, 9, 11),
    )

    assert [meal.id for meal in global_page.items] == [earlier_updated.id]
    assert [meal.id for meal in restaurant_page.items] == [earlier_updated.id]
