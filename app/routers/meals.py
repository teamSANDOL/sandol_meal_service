from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import time
from fastapi_pagination import Params, add_pagination
from fastapi_pagination.ext.sqlalchemy import paginate

from app.utils import get_db
from app.models.meals import Meal
from app.schemas.meals import MealResponse
from app.schemas.pagination import CustomPage

router = APIRouter()


@router.get("/meals", response_model=CustomPage[MealResponse])
def list_meals(db: Session = Depends(get_db), params: Params = Depends()):
    """모든 식사 데이터를 반환합니다."""
    page_data = paginate(db.query(Meal), params=params)  # 자동 페이징
    return page_data


add_pagination(router)
