from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.restaurants import OperatingHours, RestaurantSubmission, User
from app.schemas.base import BaseSchema
from app.schemas.restaurants import RestaurantRequest, SubmissionResponse, TimeRange
from app.utils.db import get_current_user, get_db
from app.utils.times import get_datetime_by_string, get_now_timestamp


router = APIRouter(prefix="/restaurants")
