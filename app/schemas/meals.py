from datetime import datetime
from typing import Literal
import pytz
from pydantic import BaseModel

# 서울 시간대 설정
SEOUL_TZ = pytz.timezone("Asia/Seoul")


class Timestamp:
    """str | datetime 을 자동 변환하는 커스텀 타입"""

    def __init__(self, value: str | datetime):
        if isinstance(value, str):
            try:
                self.value = datetime.fromisoformat(value).astimezone(
                    SEOUL_TZ
                )  # ISO 검증 + 서울 시간 변환
            except ValueError as err:
                raise ValueError(f"Invalid ISO 8601 format: {value}") from err
        elif isinstance(value, datetime):
            self.value = value.astimezone(SEOUL_TZ)  # datetime이면 서울 시간 변환
        else:
            raise TypeError(f"Expected str or datetime, got {type(value)}")

    def __str__(self):
        """Pydantic이 자동 호출하는 ISO 8601 형식 문자열"""
        return self.value.isoformat()

    def __repr__(self):
        return f"CustomDateTime({self.value.isoformat()})"

    def to_datetime(self):
        """datetime 객체 반환"""
        return self.value


class BaseMeal(BaseModel):
    """공통 Meal 모델"""
    id: int
    menu: list[str]
    registered_at: Timestamp
    meal_type: Literal["breakfast", "brunch", "lunch", "dinner"]


class MealResponse(BaseMeal):
    """개별 식사 응답 모델"""
    restaurant_id: int
    restaurant_name: str


class RestaurantMeal(BaseMeal):
    """식당 내 개별 식사 모델"""


class RestaurantMealResponse(BaseModel):
    """식당 내 모든 식사 정보를 포함하는 응답"""
    id: int
    name: str
    meals: list[RestaurantMeal]


class MealRegisterResponse(BaseModel):
    """식사 등록 응답"""
    id: str
    restaurant_id: str
    meal_type: Literal["breakfast", "brunch", "lunch", "dinner"]
    registered_at: Timestamp

class MealEditResponse(BaseModel):
    """식사 수정 응답"""
    id: str
    restaurant_id: str
    meal_type: Literal["breakfast", "brunch", "lunch", "dinner"]
    menu: list[str]
