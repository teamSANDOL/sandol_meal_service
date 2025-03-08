from enum import Enum
from pydantic import BaseModel

from app.schemas.base import Timestamp


class MealType(str, Enum):
    """식사 종류"""

    breakfast = "breakfast"
    brunch = "brunch"
    lunch = "lunch"
    dinner = "dinner"


class BaseMeal(BaseModel):
    """공통 Meal 모델"""

    menu: list[str]
    meal_type: MealType


class MealRegister(BaseMeal):
    """식사 등록 모델"""


class MealRegisterResponse(BaseModel):
    """식사 등록 응답"""

    id: int
    restaurant_id: int
    meal_type: MealType
    registered_at: Timestamp


class MealResponse(BaseMeal):
    """개별 식사 응답 모델"""

    id: int
    registered_at: Timestamp
    restaurant_id: int
    restaurant_name: str
    updated_at: Timestamp


class RestaurantMeal(MealResponse):
    """식당 내 개별 식사 모델"""


class RestaurantMealResponse(BaseModel):
    """식당 내 모든 식사 정보를 포함하는 응답"""

    id: int
    name: str
    meals: list[RestaurantMeal]


class MenuEdit(BaseModel):
    """메뉴 삭제 모델"""

    menu: str | list[str]


class MealEditResponse(BaseModel):
    """식사 수정 응답"""

    id: int
    restaurant_id: int
    meal_type: MealType
    menu: list[str]
