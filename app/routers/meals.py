from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi_pagination import Params, add_pagination
from fastapi_pagination.ext.sqlalchemy import paginate

from app.utils.db import get_admin_user, get_current_user, get_db
from app.models.meals import Meal
from app.models.user import User
from app.schemas.meals import MealResponse
from app.schemas.pagination import CustomPage

router = APIRouter(prefix="/meals")


@router.get("/", response_model=CustomPage[MealResponse])
async def list_meals(db: AsyncSession = Depends(get_db), params: Params = Depends()):
    """모든 식사 데이터를 반환합니다."""
    return await paginate(db, select(Meal), params=params)  # 비동기 페이징

@router.post("/{restaurant_id}")
async def register_meal(
    restaurant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
    ):
    """식사를 등록합니다."""

add_pagination(router)
