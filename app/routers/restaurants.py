from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi_pagination import Params, add_pagination, paginate

from app.config import logger
from app.models.restaurants import (
    OperatingHours,
    Restaurant,
    RestaurantSubmission,
)
from app.models.user import User
from app.schemas.base import BaseSchema
from app.schemas.restaurants import (
    ApproverResponse,
    RestaurantRequest,
    SubmissionResponse,
    TimeRange,
    UserSchema,
)
from app.schemas.restaurants import RestaurantSubmission as RestaurantSubmissionSchema
from app.schemas.restaurants import RestaurantResponse
from app.utils.restaurants import (
    fetch_operating_hours_dict,
    build_location_schema,
    get_submission_or_404,
    get_restaurant_or_404,
    build_operating_hours_entries,
)
from app.utils.db import get_admin_user, get_current_user, get_db
from app.schemas.pagination import CustomPage

router = APIRouter(prefix="/restaurants")


@router.post("/requests")
async def restaurant_submit_request(
    request: RestaurantRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if request.location is None or request.opening_time is None:
        raise HTTPException(
            status_code=400, detail="location, opening_time 필드는 필수입니다."
        )

    new_submission = RestaurantSubmission(
        name=request.name,
        status="pending",
        submitter=current_user.id,
        establishment_type=request.establishment_type,
        is_campus=request.location.is_campus,
        building_name=request.location.building,
        naver_map_link=request.location.map_links.get("naver")
        if request.location.map_links
        else None,
        kakao_map_link=request.location.map_links.get("kakao")
        if request.location.map_links
        else None,
        latitude=request.location.latitude,
        longitude=request.location.longitude,
    )

    try:
        db.add(new_submission)
        await db.commit()
        await db.refresh(new_submission)

        operation_hours_dict = {
            "opening_time": request.opening_time,
            "break_time": request.break_time,
            "breakfast_time": request.breakfast_time,
            "brunch_time": request.brunch_time,
            "lunch_time": request.lunch_time,
            "dinner_time": request.dinner_time,
        }

        operating_hours_entries = build_operating_hours_entries(
            operation_hours_dict, submission_id=new_submission.id
        )

        db.add_all(operating_hours_entries)
        await db.commit()

    except Exception as e:
        await db.rollback()
        logger.error("Submission 요청 처리 중 예외 발생: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류 발생")

    return BaseSchema[SubmissionResponse](
        data=SubmissionResponse(request_id=new_submission.id)
    )


@router.post("/restaurants/{request_id}/approval")
async def restaurant_submit_approval(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserSchema = Depends(get_admin_user),
):
    submission: RestaurantSubmission = await get_submission_or_404(db, request_id)
    if submission.status != "pending":
        raise HTTPException(
            status_code=400, detail="해당 제출 요청은 이미 처리되었습니다."
        )

    submission.status = "approved"
    submission.approver = current_user.id

    new_restaurant = Restaurant(
        name=submission.name,
        owner=submission.submitter,
        establishment_type=submission.establishment_type,
        is_campus=submission.is_campus,
        building_name=submission.building_name,
        naver_map_link=submission.naver_map_link,
        kakao_map_link=submission.kakao_map_link,
        latitude=submission.latitude,
        longitude=submission.longitude,
    )

    try:
        db.add(submission)
        db.add(new_restaurant)
        await db.commit()
        await db.refresh(new_restaurant)

        # 운영시간 복제 로직 공통화 적용
        operating_hours_result = await db.execute(
            select(OperatingHours).filter(OperatingHours.submission_id == request_id)
        )
        operating_hours = operating_hours_result.scalars().all()

        operating_hours_entries = [
            OperatingHours(
                type=oh.type,
                start_time=oh.start_time,
                end_time=oh.end_time,
                restaurant_id=new_restaurant.id,
            )
            for oh in operating_hours
        ]

        db.add_all(operating_hours_entries)
        await db.commit()

    except Exception as e:
        await db.rollback()
        logger.error("Approval 처리 중 예외 발생: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류 발생")

    return BaseSchema[ApproverResponse](
        data=ApproverResponse(restaurant_id=new_restaurant.id)
    )


@router.get("/requests/{request_id}")
async def restaurant_submit_get(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """GET /restaurants/requests/{request_id} 엔드포인트"""
    logger.info(
        "Get request received for submission_id: %s by user: %s",
        request_id,
        current_user.id,
    )

    submission: RestaurantSubmission = await get_submission_or_404(db, request_id)

    logger.info("Submission with id %s found", request_id)

    operating_hours_dict = await fetch_operating_hours_dict(
        db, submission_id=request_id
    )
    logger.debug(
        "Found %s operating hours for submission id %s",
        len(operating_hours_dict),
        request_id,
    )

    response_data = RestaurantSubmissionSchema(
        status=submission.status,  # type: ignore
        submitter=submission.submitter,
        submitted_time=submission.submitted_time,
        id=submission.id,
        name=submission.name,
        establishment_type=submission.establishment_type,  # type: ignore
        location=build_location_schema(
            submission.is_campus,
            building=submission.building_name,
            naver_link=submission.naver_map_link,
            kakao_link=submission.kakao_map_link,
            lat=submission.latitude,
            lon=submission.longitude,
        ),
        opening_time=operating_hours_dict.get("opening_time"),
        break_time=operating_hours_dict.get("break_time"),
        breakfast_time=operating_hours_dict.get("breakfast_time"),
        brunch_time=operating_hours_dict.get("brunch_time"),
        lunch_time=operating_hours_dict.get("lunch_time"),
        dinner_time=operating_hours_dict.get("dinner_time"),
    )

    return BaseSchema[RestaurantSubmissionSchema](data=response_data)


@router.delete("/requests/{request_id}", status_code=204)
async def restaurant_submit_delete(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """DELETE /restaurants/requests/{submission_id} 엔드포인트"""
    logger.info(
        "Delete request received for submission_id: %s by user: %s",
        request_id,
        current_user.id,
    )

    submission: RestaurantSubmission = await get_submission_or_404(db, request_id)
    if submission.submitter != current_user.id:
        logger.warning(
            "User %s does not have permission to delete submission with id %s",
            current_user.id,
            request_id,
        )
        raise HTTPException(
            status_code=403, detail="해당 제출 요청을 삭제할 권한이 없습니다."
        )

    await db.delete(submission)
    await db.commit()
    logger.info("Submission with id %s deleted successfully", request_id)


@router.get("/{restaurant_id}")
async def get_restaurant(
    restaurant_id: int,
    db: AsyncSession = Depends(get_db),
):
    """GET /restaurants/{restaurant_id} 엔드포인트"""
    logger.info("Get request received for restaurant_id: %s", restaurant_id)

    restaurant = await get_restaurant_or_404(db, restaurant_id)

    operating_hours_dict = await fetch_operating_hours_dict(
        db, restaurant_id=restaurant_id
    )
    logger.debug(
        "Found %s operating hours for restaurant id %s",
        len(operating_hours_dict),
        restaurant_id,
    )

    response_data = RestaurantResponse(
        id=restaurant.id,
        name=restaurant.name,
        owner=restaurant.owner,
        establishment_type=restaurant.establishment_type,  # type: ignore
        location=build_location_schema(
            is_campus=restaurant.is_campus,
            building=restaurant.building_name,
            naver_link=restaurant.naver_map_link,
            kakao_link=restaurant.kakao_map_link,
            lat=restaurant.latitude,
            lon=restaurant.longitude,
        ),
        opening_time=operating_hours_dict.get("opening_time"),
        break_time=operating_hours_dict.get("break_time"),
        breakfast_time=operating_hours_dict.get("breakfast_time"),
        brunch_time=operating_hours_dict.get("brunch_time"),
        lunch_time=operating_hours_dict.get("lunch_time"),
        dinner_time=operating_hours_dict.get("dinner_time"),
    )

    return BaseSchema[RestaurantResponse](data=response_data)


@router.get("/", response_model=CustomPage[RestaurantResponse])
async def get_restaurants(
    db: AsyncSession = Depends(get_db), params: Params = Depends()
):
    """모든 업체 데이터를 반환합니다."""
    # 1️⃣ SQLAlchemy ORM 객체 가져오기
    result = await db.execute(select(Restaurant))
    restaurants = result.scalars().all()

    # 2️⃣ ORM 객체 → Pydantic 변환
    restaurant_schemas = []
    for restaurant in restaurants:
        operating_hours_result = await db.execute(
            select(OperatingHours).filter(OperatingHours.restaurant_id == restaurant.id)
        )
        operating_hours = operating_hours_result.scalars().all()
        operating_hours_dict = {
            operating_hour.type: TimeRange(
                start=operating_hour.start_time, end=operating_hour.end_time
            )
            for operating_hour in operating_hours
        }
        logger.debug(
            "Found %s operating hours for restaurant id %s",
            len(operating_hours),
            restaurant.id,
        )

        response_data = RestaurantResponse(
            id=restaurant.id,
            name=restaurant.name,
            owner=restaurant.owner,
            establishment_type=restaurant.establishment_type,  # type: ignore
            location=build_location_schema(
                is_campus=restaurant.is_campus,
                building=restaurant.building_name,
                naver_link=restaurant.naver_map_link,
                kakao_link=restaurant.kakao_map_link,
                lat=restaurant.latitude,
                lon=restaurant.longitude,
            ),
            opening_time=operating_hours_dict.get("opening_time"),
            break_time=operating_hours_dict.get("break_time"),
            breakfast_time=operating_hours_dict.get("breakfast_time"),
            brunch_time=operating_hours_dict.get("brunch_time"),
            lunch_time=operating_hours_dict.get("lunch_time"),
            dinner_time=operating_hours_dict.get("dinner_time"),
        )
        restaurant_schemas.append(response_data)

    return paginate(restaurant_schemas, params)


add_pagination(router)
