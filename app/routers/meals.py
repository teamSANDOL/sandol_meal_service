from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from fastapi_pagination import Params, add_pagination
from fastapi_pagination import paginate

from app.utils.db import get_current_user, get_db
from app.models.meals import Meal, MealType
from app.models.restaurants import Restaurant
from app.models.user import User
from app.schemas.base import BaseSchema
from app.schemas.meals import (
    MealResponse,
    MealRegister,
    MealRegisterResponse,
    Timestamp,
)
from app.schemas.meals import MealType as MealTypeSchema
from app.schemas.pagination import CustomPage

router = APIRouter(prefix="/meals")


@router.get("", response_model=CustomPage[MealResponse])
async def list_meals(db: AsyncSession = Depends(get_db), params: Params = Depends()):
    """모든 식사 데이터를 반환합니다."""
    result = await db.execute(
        select(Meal)
        .options(selectinload(Meal.restaurant))
        .options(selectinload(Meal.meal_type))
    )
    meals = result.scalars().all()

    # ✅ Meal 객체를 MealResponse Pydantic 모델로 변환
    response_data = [
        MealResponse(
            id=meal.id,
            menu=meal.menu,
            meal_type=MealTypeSchema(meal.meal_type.name),  # MealType Enum을 str로 변환
            restaurant_id=meal.restaurant_id,
            restaurant_name=meal.restaurant.name,
            registered_at=meal.registered_at,
        )
        for meal in meals
    ]

    return paginate(response_data, params)


@router.get("/{meal_id}", response_model=BaseSchema[MealResponse])
async def get_meal(
    meal_id: int,
    db: AsyncSession = Depends(get_db),
):
    """특정 식사 데이터를 반환합니다."""
    result = await db.execute(
        select(Meal)
        .where(Meal.id == meal_id)
        .options(selectinload(Meal.restaurant))
        .options(selectinload(Meal.meal_type))
    )
    meal: Meal | None = result.scalars().first()

    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    response_data = MealResponse(
        id=meal.id,
        menu=meal.menu,
        meal_type=MealTypeSchema(meal.meal_type.name),
        restaurant_id=meal.restaurant_id,
        restaurant_name=meal.restaurant.name,
        registered_at=meal.registered_at,  # Timestamp
    )

    return BaseSchema[MealResponse](data=response_data)


@router.get("/restaurant/{restaurant_id}", response_model=CustomPage[MealResponse])
async def list_meals_by_restaurant(
    restaurant_id: int,
    db: AsyncSession = Depends(get_db),
    params: Params = Depends(),
):
    """특정 식당의 모든 식사 데이터를 반환합니다."""
    result = await db.execute(
        select(Meal)
        .where(Meal.restaurant_id == restaurant_id)
        .options(selectinload(Meal.restaurant))
        .options(selectinload(Meal.meal_type))
    )
    meals = result.scalars().all()

    response_data: list[MealResponse] = [
        MealResponse(
            id=meal.id,
            menu=meal.menu,
            meal_type=MealTypeSchema(meal.meal_type.name),
            restaurant_id=meal.restaurant_id,
            restaurant_name=meal.restaurant.name,
            registered_at=meal.registered_at,
        )
        for meal in meals
    ]

    return paginate(response_data, params)


@router.delete("/{meal_id}", status_code=204)
async def delete_meal(
    meal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """특정 식사 데이터를 삭제합니다."""
    result = await db.execute(select(Meal).where(Meal.id == meal_id))
    meal: Meal | None = result.scalars().first()

    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")

    # restaurant_id와 current_user.id를 사용해 db 조회
    restaurant_result = await db.execute(
        select(Restaurant).where(
            Restaurant.id == meal.restaurant_id,
            or_(
                Restaurant.owner == current_user.id,
                Restaurant.managers.any(User.id == current_user.id),
            ),
        )
    )
    restaurant: Restaurant | None = restaurant_result.scalars().first()
    if not restaurant:
        raise HTTPException(
            status_code=404,
            detail="Restaurant not found or you do not have permission to access it",
        )

    await db.delete(meal)
    await db.commit()


@router.post("/{restaurant_id}")
async def register_meal(
    restaurant_id: int,
    meal_register: MealRegister,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """식사를 등록합니다."""
    # restaurant_id와 current_user.id를 사용해 db 조회
    restaurant_result = await db.execute(
        select(Restaurant).where(
            Restaurant.id == restaurant_id,
            or_(
                Restaurant.owner == current_user.id,
                Restaurant.managers.any(User.id == current_user.id),
            ),
        )
    )
    restaurant: Restaurant | None = restaurant_result.scalars().first()
    if not restaurant:
        raise HTTPException(
            status_code=404,
            detail="Restaurant not found or you do not have permission to access it",
        )

    meal_type_result = await db.execute(
        select(MealType).where(MealType.name == meal_register.meal_type)
    )
    meal_type = meal_type_result.scalars().first()
    if not meal_type:
        raise HTTPException(status_code=404, detail="Meal type not found")

    new_meal = Meal(
        restaurant_id=restaurant_id,
        menu=meal_register.menu,
        meal_type_id=meal_type.id,
    )

    db.add(new_meal)
    await db.commit()
    await db.refresh(new_meal)

    meal_type_enum = MealTypeSchema(meal_type.name)
    time_stamp_schema = Timestamp.convert_to_kst(new_meal.registered_at)
    response_data = MealRegisterResponse(
        id=new_meal.id,
        restaurant_id=new_meal.restaurant_id,
        meal_type=meal_type_enum,
        registered_at=time_stamp_schema,
    )
    return BaseSchema[MealRegisterResponse](data=response_data)


add_pagination(router)
