"""식사 관련 데이터 모델 스키마 모듈

이 모듈은 식사 관련 데이터 모델을 정의합니다. Pydantic을 사용하여 데이터 유효성 검사를 수행하며,
식사 종류, 식사 등록, 식사 응답, 메뉴 수정 등의 다양한 모델을 포함합니다.

클래스 목록:
    - MealType: 식사 종류를 나타내는 Enum 클래스
    - BaseMeal: 공통 Meal 모델
    - MealRegister: 식사 등록 모델
    - MealRegisterResponse: 식사 등록 응답 모델
    - MealResponse: 개별 식사 응답 모델
    - MenuEdit: 메뉴 수정 모델
    - MealEditResponse: 식사 수정 응답 모델
"""

from typing import Annotated
from datetime import datetime
from enum import Enum
from pydantic import BaseModel

from app.schemas.base import Timestamp as Tsp

Timestamp = Annotated[datetime, Tsp]


class MealType(str, Enum):
    """식사 종류를 나타내는 Enum 클래스

    Attributes:
        breakfast (str): 아침 식사
        brunch (str): 브런치
        lunch (str): 점심 식사
        dinner (str): 저녁 식사
    """

    breakfast = "breakfast"
    brunch = "brunch"
    lunch = "lunch"
    dinner = "dinner"


class BaseMeal(BaseModel):
    """공통 Meal 모델

    Attributes:
        menu (list[str]): 메뉴 목록
        meal_type (MealType): 식사 종류
    """

    menu: list[str]
    meal_type: MealType


class MealRegister(BaseMeal):
    """식사 등록 모델

    BaseMeal을 상속받아 추가적인 필드를 포함하지 않음
    """


class MealRegisterResponse(BaseModel):
    """식사 등록 응답 모델

    Attributes:
        id (int): 식사 ID
        restaurant_id (int): 식당 ID
        meal_type (MealType): 식사 종류
        registered_at (Timestamp): 등록 시간
    """

    id: int
    restaurant_id: int
    meal_type: MealType
    registered_at: Timestamp


class MealResponse(BaseMeal):
    """개별 식사 응답 모델

    Attributes:
        id (int): 식사 ID
        registered_at (Timestamp): 등록 시간
        restaurant_id (int): 식당 ID
        restaurant_name (str): 식당 이름
        updated_at (Timestamp): 수정 시간
    """

    id: int
    registered_at: Timestamp
    restaurant_id: int
    restaurant_name: str
    updated_at: Timestamp


class MenuEdit(BaseModel):
    """메뉴 수정 모델

    Attributes:
        menu (str | list[str]): 수정할 메뉴 목록
    """

    menu: str | list[str]


class MealEditResponse(BaseModel):
    """식사 수정 응답 모델

    Attributes:
        id (int): 식사 ID
        restaurant_id (int): 식당 ID
        meal_type (MealType): 식사 종류
        menu (list[str]): 메뉴 목록
    """

    id: int
    restaurant_id: int
    meal_type: MealType
    menu: list[str]
