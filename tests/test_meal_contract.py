from datetime import date

import pytest
from pydantic import ValidationError

from app.models.meals import Meal
from app.schemas.meals import MealRegister, MealRegisterResponse
from app.utils.meals import upsert_meal


def test_meal_schemas_accept_only_date() -> None:
    payload = {"menu": ["밥"], "meal_type": "lunch", "date": date(2026, 9, 12)}

    meal = MealRegister.model_validate(payload)
    response = MealRegisterResponse.model_validate(
        {
            **payload,
            "id": 1,
            "restaurant_id": 1,
            "registered_at": "2026-09-12T00:00:00Z",
        }
    )

    assert meal.date == date(2026, 9, 12)
    assert response.date == date(2026, 9, 12)


def test_meal_schemas_reject_served_date_alias() -> None:
    payload = {"menu": ["밥"], "meal_type": "lunch", "served_date": "2026-09-12"}

    with pytest.raises(ValidationError):
        MealRegister.model_validate(payload)


def test_meal_model_exposes_only_date_column() -> None:
    assert hasattr(Meal, "date")
    assert not hasattr(Meal, "served_date")


def test_upsert_meal_requires_date_keyword() -> None:
    assert "date" in upsert_meal.__annotations__
    assert "served_date" not in upsert_meal.__annotations__
