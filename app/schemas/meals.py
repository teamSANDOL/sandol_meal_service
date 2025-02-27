from datetime import datetime
from typing import Literal
import pytz
from pydantic import BaseModel, GetCoreSchemaHandler
from pydantic_core import core_schema

# 서울 시간대 설정
SEOUL_TZ = pytz.timezone("Asia/Seoul")


class Timestamp:
    """KST(서울 시간)으로 자동 변환되는 datetime 필드"""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler: GetCoreSchemaHandler):
        """Pydantic이 사용할 스키마를 정의"""
        return core_schema.no_info_after_validator_function(cls.convert_to_kst, handler.generate_schema(datetime))

    @classmethod
    def convert_to_kst(cls, value: str | datetime) -> datetime:
        """ISO 8601 문자열 또는 datetime을 받아 KST 변환"""
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is None:
                    # ✅ 타임존이 없는 경우, 기본적으로 KST로 간주
                    dt = dt.replace(tzinfo=SEOUL_TZ)
                else:
                    # ✅ 타임존이 있는 경우, KST로 변환
                    dt = dt.astimezone(SEOUL_TZ)
                return dt
            except ValueError as err:
                raise ValueError(f"Invalid ISO 8601 format: {value}") from err

        elif isinstance(value, datetime):
            if value.tzinfo is None:
                # ✅ datetime 객체에 타임존이 없으면 KST로 간주
                return value.replace(tzinfo=SEOUL_TZ)
            else:
                return value.astimezone(SEOUL_TZ)
        else:
            raise TypeError(f"Expected str or datetime, got {type(value)}")


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
