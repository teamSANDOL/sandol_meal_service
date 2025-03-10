from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_pagination import Params, add_pagination, paginate
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.config import Config, logger
from app.models.meals import Meal
from app.models.user import User
from app.schemas.base import BaseSchema
from app.schemas.meals import (
    MenuEdit,
    MealEditResponse,
    MealRegister,
    MealRegisterResponse,
    MealResponse,
)
from app.schemas.meals import MealType as MealTypeSchema
from app.schemas.pagination import CustomPage
from app.utils.db import get_current_user, get_db
from app.utils.meals import (
    apply_date_filter,
    check_restaurant_permission,
    get_meal_type,
    register_meal_transaction,
    delete_meal_transaction,
    update_meal_menu_transaction,
    update_meal_menu,
    delete_meal_menu,
)

router = APIRouter(prefix="/meals")


@router.get("", response_model=CustomPage[MealResponse])
async def list_meals(
    start_date: str = Query(None, description="검색 시작 날짜 (YYYY-MM-DD)"),
    end_date: str = Query(None, description="검색 종료 날짜 (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    params: Params = Depends(),
):
    """모든 식사 데이터를 반환합니다."""
    logger.info("Fetching all meals with filters: start_date=%s, end_date=%s", start_date, end_date)

    query = (
        select(Meal)
        .options(selectinload(Meal.restaurant))
        .options(selectinload(Meal.meal_type))
    )

    query = await apply_date_filter(query, start_date, end_date)

    result = await db.execute(query)
    meals = result.scalars().all()

    logger.info("Retrieved %d meals", len(meals))

    response_data = [
        MealResponse(
            id=meal.id,
            menu=meal.menu,
            meal_type=MealTypeSchema(meal.meal_type.name),
            restaurant_id=meal.restaurant_id,
            restaurant_name=meal.restaurant.name,
            registered_at=meal.registered_at,
            updated_at=meal.updated_at,
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
    logger.info("Fetching meal with id: %d", meal_id)

    result = await db.execute(
        select(Meal)
        .where(Meal.id == meal_id)
        .options(selectinload(Meal.restaurant))
        .options(selectinload(Meal.meal_type))
    )
    meal = result.scalars().first()

    if not meal:
        logger.warning("Meal with id %d not found", meal_id)
        raise HTTPException(status_code=404, detail="Meal not found")

    logger.info("Meal found: %d", meal.id)

    response_data = MealResponse(
        id=meal.id,
        menu=meal.menu,
        meal_type=MealTypeSchema(meal.meal_type.name),
        restaurant_id=meal.restaurant_id,
        restaurant_name=meal.restaurant.name,
        registered_at=meal.registered_at,
        updated_at=meal.updated_at,
    )

    return BaseSchema[MealResponse](data=response_data)


@router.get("/restaurant/{restaurant_id}", response_model=CustomPage[MealResponse])
async def list_meals_by_restaurant(
    restaurant_id: int,
    start_date: str = Query(None, description="검색 시작 날짜 (YYYY-MM-DD)"),
    end_date: str = Query(None, description="검색 종료 날짜 (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    params: Params = Depends(),
):
    """특정 식당의 모든 식사 데이터를 반환합니다."""
    logger.info("Fetching meals for restaurant_id=%d with filters: start_date=%s, end_date=%s", restaurant_id, start_date, end_date)

    query = (
        select(Meal)
        .where(Meal.restaurant_id == restaurant_id)
        .options(selectinload(Meal.restaurant))
        .options(selectinload(Meal.meal_type))
    )

    query = await apply_date_filter(query, start_date, end_date)

    result = await db.execute(query)
    meals = result.scalars().all()

    logger.info("Retrieved %d meals for restaurant_id=%d", len(meals), restaurant_id)

    response_data = [
        MealResponse(
            id=meal.id,
            menu=meal.menu,
            meal_type=MealTypeSchema(meal.meal_type.name),
            restaurant_id=meal.restaurant_id,
            restaurant_name=meal.restaurant.name,
            registered_at=meal.registered_at,
            updated_at=meal.updated_at,
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
    logger.info("User %d attempting to delete meal %d", current_user.id, meal_id)

    result = await db.execute(select(Meal).where(Meal.id == meal_id))
    meal = result.scalars().first()

    if not meal:
        logger.warning("Meal with id %d not found", meal_id)
        raise HTTPException(status_code=404, detail="Meal not found")

    await check_restaurant_permission(db, meal.restaurant_id, current_user.id)
    await delete_meal_transaction(db, meal)

    logger.info("Meal %d successfully deleted by user %d", meal_id, current_user.id)


@router.post("/{restaurant_id}")
async def register_meal(
    restaurant_id: int,
    meal_register: MealRegister,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """식사를 등록합니다."""
    logger.info("User %d attempting to register meal for restaurant %d", current_user.id, restaurant_id)

    await check_restaurant_permission(db, restaurant_id, current_user.id)
    meal_type = await get_meal_type(db, meal_register.meal_type)

    new_meal = Meal(
        restaurant_id=restaurant_id,
        menu=meal_register.menu,
        meal_type_id=meal_type.id,
    )

    await register_meal_transaction(db, new_meal)

    logger.info("Meal %d successfully registered by user %d", new_meal.id, current_user.id)

    response_data = MealRegisterResponse(
        id=new_meal.id,
        restaurant_id=new_meal.restaurant_id,
        meal_type=MealTypeSchema(meal_type.name),
        registered_at=new_meal.registered_at,
    )

    return BaseSchema[MealRegisterResponse](data=response_data)


@router.delete("/{meal_id}/menus", status_code=204)
async def delete_meal_menu(
    meal_id: int,
    menu_delete: MenuEdit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """특정 식사의 메뉴를 삭제합니다."""
    logger.info("User %d attempting to delete menu for meal %d", current_user.id, meal_id)

    result = await db.execute(select(Meal).where(Meal.id == meal_id))
    meal = result.scalars().first()

    if not meal:
        logger.warning("Meal with id %d not found", meal_id)
        raise HTTPException(status_code=404, detail="Meal not found")

    await check_restaurant_permission(db, meal.restaurant_id, current_user.id)

    updated_menu = delete_meal_menu(meal, menu_delete.menu)
    await update_meal_menu_transaction(db, meal, updated_menu)

    logger.info("Menu successfully deleted for meal %d", meal.id)


@router.patch("/{meal_id}/menus")
async def edit_meal_menu(
    meal_id: int,
    menu_edit: MenuEdit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """특정 식사의 메뉴를 수정합니다."""
    logger.info("User %d attempting to edit menu for meal %d", current_user.id, meal_id)

    result = await db.execute(select(Meal).where(Meal.id == meal_id))
    meal = result.scalars().first()

    if not meal:
        logger.warning("Meal with id %d not found", meal_id)
        raise HTTPException(status_code=404, detail="Meal not found")

    await check_restaurant_permission(db, meal.restaurant_id, current_user.id)

    updated_menu = update_meal_menu(meal, menu_edit.menu)
    await update_meal_menu_transaction(db, meal, updated_menu)

    logger.info("Menu successfully updated for meal %d", meal.id)

    response_data = MealEditResponse(
        id=meal.id,
        restaurant_id=meal.restaurant_id,
        meal_type=MealTypeSchema(meal.meal_type.name),
        menu=meal.menu,
    )

    return BaseSchema[MealEditResponse](data=response_data)


add_pagination(router)
