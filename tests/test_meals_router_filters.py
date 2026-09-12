"""Focused query-filter tests for the meal list router."""

import datetime as dt

import pytest
from fastapi_pagination import Params
from sqlalchemy import select

from app.models.meals import MealType
from app.routers.meals import list_meals_by_restaurant
from app.schemas.meals import MealType as MealTypeSchema
from app.utils.meals import upsert_meal


@pytest.mark.asyncio
async def test_restaurant_list_applies_meal_type_filter(db) -> None:
    """Restaurant and meal-type filters narrow the same API response."""
    lunch = await db.scalar(select(MealType).where(MealType.name == "lunch"))
    dinner = await db.scalar(select(MealType).where(MealType.name == "dinner"))
    assert lunch is not None
    assert dinner is not None

    await upsert_meal(
        db,
        restaurant_id=1,
        meal_type_id=lunch.id,
        menu=["TIP 점심"],
        date=dt.date(2026, 9, 12),
    )
    await upsert_meal(
        db,
        restaurant_id=1,
        meal_type_id=dinner.id,
        menu=["TIP 저녁"],
        date=dt.date(2026, 9, 12),
    )
    await upsert_meal(
        db,
        restaurant_id=2,
        meal_type_id=lunch.id,
        menu=["E동 점심"],
        date=dt.date(2026, 9, 12),
    )
    await db.commit()

    page = await list_meals_by_restaurant(
        restaurant_id=1,
        db=db,
        params=Params(page=1, size=100),
        start_date=None,
        end_date=None,
        meal_type=MealTypeSchema.lunch,
    )

    assert page.total == 1
    assert [(meal.restaurant_id, meal.meal_type, meal.menu) for meal in page.items] == [
        (1, MealTypeSchema.lunch, ["TIP 점심"])
    ]
