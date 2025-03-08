from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_pagination import Params, add_pagination, paginate
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.config import Config, logger
from app.models.meals import Meal, MealType
from app.models.restaurants import Restaurant
from app.models.user import User
from app.schemas.base import BaseSchema
from app.schemas.meals import (
    MenuEdit,
    MealEditResponse,
    MealRegister,
    MealRegisterResponse,
    MealResponse,
    Timestamp,
)
from app.schemas.meals import MealType as MealTypeSchema
from app.schemas.pagination import CustomPage
from app.utils.db import get_current_user, get_db

router = APIRouter(prefix="/meals")


@router.get("", response_model=CustomPage[MealResponse])
async def list_meals(
    start_date: str = Query(None, description="검색 시작 날짜 (YYYY-MM-DD)"),
    end_date: str = Query(None, description="검색 종료 날짜 (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    params: Params = Depends(),
):
    """모든 식사 데이터를 반환합니다."""
    query = (
        select(Meal)
        .options(selectinload(Meal.restaurant))
        .options(selectinload(Meal.meal_type))
    )

    # 문자열을 datetime.date로 변환
    try:
        start_date_dt = (
            datetime.strptime(start_date, "%Y-%m-%d")
            .replace(tzinfo=Config.TZ)
            .astimezone(timezone.utc)
            if start_date
            else None
        )
        end_date_dt = (
            datetime.strptime(end_date, "%Y-%m-%d")
            .replace(tzinfo=Config.TZ)
            .astimezone(timezone.utc)
            if end_date
            else None
        )
    except ValueError:
        raise HTTPException(
            status_code=400, detail="날짜 형식이 올바르지 않습니다. (YYYY-MM-DD)"
        )

    # 날짜 필터링 적용
    if start_date_dt and end_date_dt:
        if start_date_dt > end_date_dt:
            query = query.where(Meal.updated_at.between(end_date_dt, start_date_dt))
        else:
            query = query.where(Meal.updated_at.between(start_date_dt, end_date_dt))
    elif start_date_dt:
        query = query.where(Meal.updated_at >= start_date_dt)
    elif end_date_dt:
        query = query.where(Meal.updated_at <= end_date_dt)

    result = await db.execute(query)
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
        updated_at=meal.updated_at,  # Timestamp
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
    query = (
        select(Meal)
        .where(Meal.restaurant_id == restaurant_id)
        .options(selectinload(Meal.restaurant))
        .options(selectinload(Meal.meal_type))
    )

    # 문자열을 datetime.date로 변환
    try:
        start_date_dt = (
            datetime.strptime(start_date, "%Y-%m-%d")
            .replace(tzinfo=Config.TZ)
            .astimezone(timezone.utc)
            if start_date
            else None
        )
        end_date_dt = (
            datetime.strptime(end_date, "%Y-%m-%d")
            .replace(tzinfo=Config.TZ)
            .astimezone(timezone.utc)
            if end_date
            else None
        )
    except ValueError:
        raise HTTPException(
            status_code=400, detail="날짜 형식이 올바르지 않습니다. (YYYY-MM-DD)"
        )

    # 날짜 필터링 적용
    if start_date_dt and end_date_dt:
        if start_date_dt > end_date_dt:
            query = query.where(Meal.updated_at.between(end_date_dt, start_date_dt))
        else:
            query = query.where(Meal.updated_at.between(start_date_dt, end_date_dt))
    elif start_date_dt:
        query = query.where(Meal.updated_at >= start_date_dt)
    elif end_date_dt:
        query = query.where(Meal.updated_at <= end_date_dt)

    result = await db.execute(query)
    meals = result.scalars().all()

    response_data: list[MealResponse] = [
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
    logger.info(
        f"Attempting to delete menu from meal_id: {meal_id} by user_id: {current_user.id}"
    )
    logger.debug(f"menu data received: {menu_delete}")

    result = await db.execute(
        select(Meal)
        .where(Meal.id == meal_id)
        .options(selectinload(Meal.restaurant))
        .options(selectinload(Meal.meal_type))
    )
    meal: Meal | None = result.scalars().first()

    if not meal:
        logger.error(f"Meal with id {meal_id} not found")
        raise HTTPException(status_code=404, detail="Meal not found")

    logger.debug(f"Meal found: {meal}")

    if meal.restaurant.owner != current_user.id:
        logger.error(
            f"User {current_user.id} does not have permission to delete menu from meal {meal_id}"
        )
        raise HTTPException(
            status_code=403, detail="You do not have permission to access it"
        )

    logger.debug(
        f"User {current_user.id} has permission to delete menu from meal {meal_id}"
    )

    menu_list = meal.menu.copy()
    logger.debug(f"Current menu: {menu_list}")

    if isinstance(menu_delete.menu, str) and menu_delete.menu in menu_list:
        menu_list.remove(menu_delete.menu)
        logger.info(f"Removed menu {menu_delete.menu} from meal {meal_id}")
    else:
        for menu in menu_delete.menu:
            if menu in menu_list:
                menu_list.remove(menu)
                logger.info(f"Removed menu {menu} from meal {meal_id}")
    meal.menu = menu_list.copy()
    logger.debug(f"Updated menu_list: {menu_list}")

    db.add(meal)
    await db.commit()
    await db.refresh(meal)
    logger.info(f"Successfully deleted menus from meal {meal_id}")
    logger.debug(f"Updated meal: {meal.menu}")


@router.patch("/{meal_id}/menus")
async def edit_meal_menu(
    meal_id: int,
    menu_edit: MenuEdit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """특정 식사의 메뉴를 수정합니다."""
    logger.info(
        f"Attempting to edit menu from meal_id: {meal_id} by user_id: {current_user.id}"
    )
    logger.debug(f"menu data received: {menu_edit}")

    result = await db.execute(
        select(Meal)
        .where(Meal.id == meal_id)
        .options(selectinload(Meal.restaurant))
        .options(selectinload(Meal.meal_type))
    )
    meal: Meal | None = result.scalars().first()

    if not meal:
        logger.error(f"Meal with id {meal_id} not found")
        raise HTTPException(status_code=404, detail="Meal not found")

    logger.debug(f"Meal found: {meal}")

    if meal.restaurant.owner != current_user.id:
        if current_user.id in [manager.id for manager in meal.restaurant.managers]:
            logger.info(f"User {current_user.id} is a manager of the restaurant")
        else:
            logger.error(
                f"User {current_user.id} does not have permission to edit menu from meal {meal_id}"
            )
            raise HTTPException(
                status_code=403, detail="You do not have permission to access it"
            )

    logger.debug(
        f"User {current_user.id} has permission to edit menu from meal {meal_id}"
    )

    menu_list = meal.menu.copy()
    logger.debug(f"Current menu: {menu_list}")

    if isinstance(menu_edit.menu, str):
        menu_list.append(menu_edit.menu)
        logger.info(f"Added menu {menu_edit.menu} to meal {meal_id}")
    else:
        for menu in menu_edit.menu:
            menu_list.append(menu)
            logger.info(f"Added menu {menu} to meal {meal_id}")
    meal.menu = menu_list.copy()
    logger.debug(f"Updated menu_list: {menu_list}")

    db.add(meal)
    await db.commit()
    await db.refresh(meal)
    logger.info(f"Successfully edited menus from meal {meal_id}")
    logger.debug(f"Updated meal: {meal.menu}")

    response_data = MealEditResponse(
        id=meal.id,
        restaurant_id=meal.restaurant_id,
        meal_type=MealTypeSchema(meal.meal_type.name),
        menu=meal.menu,
    )

    return BaseSchema[MealEditResponse](data=response_data)


add_pagination(router)
