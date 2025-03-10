from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import or_, Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.config import Config, logger
from app.models.meals import Meal, MealType
from app.models.restaurants import Restaurant
from app.models.user import User


async def apply_date_filter(query: Select, start_date: str | None, end_date: str | None) -> Select:
    """날짜 필터링을 적용하는 헬퍼 함수"""
    logger.debug("apply_date_filter called with start_date=%s, end_date=%s", start_date, end_date)

    try:
        start_date_dt = (
            datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=Config.TZ).astimezone(timezone.utc)
            if start_date else None
        )
        end_date_dt = (
            datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=Config.TZ).astimezone(timezone.utc)
            if end_date else None
        )
    except ValueError:
        logger.warning("Invalid date format received: start_date=%s, end_date=%s", start_date, end_date)
        raise HTTPException(status_code=400, detail="날짜 형식이 올바르지 않습니다. (YYYY-MM-DD)")

    if start_date_dt and end_date_dt:
        if start_date_dt > end_date_dt:
            logger.info("Reversing date range: %s -> %s", start_date_dt, end_date_dt)
            query = query.where(Meal.updated_at.between(end_date_dt, start_date_dt))
        else:
            query = query.where(Meal.updated_at.between(start_date_dt, end_date_dt))
    elif start_date_dt:
        query = query.where(Meal.updated_at >= start_date_dt)
    elif end_date_dt:
        query = query.where(Meal.updated_at <= end_date_dt)

    logger.debug("Query after applying date filter: %s", query)
    return query


async def check_restaurant_permission(db: AsyncSession, restaurant_id: int, user_id: int) -> Restaurant:
    """사용자가 특정 식당에 대한 권한을 가지고 있는지 확인하는 헬퍼 함수"""
    logger.debug("Checking permission for user %s on restaurant %s", user_id, restaurant_id)

    result = await db.execute(
        select(Restaurant).where(
            Restaurant.id == restaurant_id,
            or_(
                Restaurant.owner == user_id,
                Restaurant.managers.any(User.id == user_id),
            ),
        )
    )
    restaurant = result.scalars().first()

    if not restaurant:
        logger.warning("User %s has no permission for restaurant %s", user_id, restaurant_id)
        raise HTTPException(status_code=403, detail="해당 식당에 접근할 권한이 없습니다.")

    logger.info("Permission granted for user %s on restaurant %s", user_id, restaurant_id)
    return restaurant


async def get_meal_type(db: AsyncSession, meal_type_name: str) -> MealType:
    """식사 유형(MealType)을 가져오는 헬퍼 함수"""
    logger.debug("Fetching MealType: %s", meal_type_name)

    meal_type_result = await db.execute(select(MealType).where(MealType.name == meal_type_name))
    meal_type = meal_type_result.scalars().first()

    if not meal_type:
        logger.warning("MealType not found: %s", meal_type_name)
        raise HTTPException(status_code=404, detail="Meal type not found")

    logger.info("MealType found: %s", meal_type.name)
    return meal_type


async def register_meal_transaction(db: AsyncSession, new_meal: Meal):
    """식사를 등록하는 트랜잭션 처리"""
    logger.info("Registering meal: %s", new_meal)

    try:
        db.add(new_meal)
        await db.commit()
        await db.refresh(new_meal)
        logger.info("Meal successfully registered: %s", new_meal.id)
    except Exception as e:
        await db.rollback()
        logger.error("Meal 등록 중 에러 발생: %s", e)
        raise HTTPException(status_code=500, detail="식사 등록 중 오류가 발생했습니다.")


async def delete_meal_transaction(db: AsyncSession, meal: Meal):
    """식사를 삭제하는 트랜잭션 처리"""
    logger.info("Deleting meal: %s", meal.id)

    try:
        await db.delete(meal)
        await db.commit()
        logger.info("Meal successfully deleted: %s", meal.id)
    except Exception as e:
        await db.rollback()
        logger.error("Meal 삭제 중 에러 발생: %s", e)
        raise HTTPException(status_code=500, detail="식사 삭제 중 오류가 발생했습니다.")


async def update_meal_menu_transaction(db: AsyncSession, meal: Meal, updated_menu: list[str]):
    """식사 메뉴를 수정하는 트랜잭션 처리"""
    logger.info("Updating meal menu for meal_id=%s with new menu: %s", meal.id, updated_menu)

    try:
        meal.menu = updated_menu
        db.add(meal)
        await db.commit()
        await db.refresh(meal)
        logger.info("Meal menu successfully updated: %s", meal.id)
    except Exception as e:
        await db.rollback()
        logger.error("Meal 메뉴 수정 중 에러 발생: %s", e)
        raise HTTPException(status_code=500, detail="식사 메뉴 수정 중 오류가 발생했습니다.")


def update_meal_menu(meal: Meal, menu_edit_list: list[str]) -> list[str]:
    """식사 메뉴를 수정하는 로직"""
    logger.debug("Updating menu for meal_id=%s. Current menu: %s", meal.id, meal.menu)

    menu_list = meal.menu.copy()
    for menu in menu_edit_list:
        if menu not in menu_list:
            menu_list.append(menu)

    logger.info("Updated menu for meal_id=%s: %s", meal.id, menu_list)
    return menu_list


def delete_meal_menu(meal: Meal, menu_delete_list: list[str]) -> list[str]:
    """식사 메뉴를 삭제하는 로직"""
    logger.debug("Deleting menu items from meal_id=%s. Current menu: %s", meal.id, meal.menu)

    menu_list = meal.menu.copy()
    for menu in menu_delete_list:
        if menu in menu_list:
            menu_list.remove(menu)

    logger.info("Updated menu after deletion for meal_id=%s: %s", meal.id, menu_list)
    return menu_list
