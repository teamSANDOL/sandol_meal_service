from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import logger
from app.models.restaurants import (
    OperatingHours,
    Restaurant,
    RestaurantSubmission,
    User,
)
from app.schemas.base import BaseSchema
from app.schemas.restaurants import (
    ApproverResponse,
    RestaurantRequest,
    SubmissionResponse,
    TimeRange,
    UserSchema,
)
from app.utils.db import get_admin_user, get_current_user, get_db
from app.utils.times import get_datetime_by_string

router = APIRouter(prefix="/restaurants")


@router.post("/requests")
async def restaurant_submit_request(
    request: RestaurantRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """POST /restaurants/requests 엔드포인트"""
    logger.info("Submission request received from user: %s", current_user.id)

    if request.location is None:
        logger.warning("Location field is missing in the request")
        raise HTTPException(status_code=400, detail="location 필드는 필수입니다.")
    if request.opening_time is None:
        logger.warning("Opening time field is missing in the request")
        raise HTTPException(status_code=400, detail="opening_time 필드는 필수입니다.")

    new_submission = RestaurantSubmission(
        name=request.name,
        status="pending",
        submitter=current_user.id,
        submitted_time=datetime.now(),
        location_type=request.location.type,
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

    db.add(new_submission)
    await db.commit()  # 먼저 커밋하여 ID 확보
    await db.refresh(new_submission)
    logger.info("New submission created with id: %s", new_submission.id)

    operation_hours_dict: dict[str, TimeRange | None] = {
        "opening_time": request.opening_time,
        "break_time": request.break_time,
        "breakfast_time": request.breakfast_time,
        "brunch_time": request.brunch_time,
        "lunch_time": request.lunch_time,
        "dinner_time": request.dinner_time,
    }
    operating_hours_entries = []
    for key, value in operation_hours_dict.items():
        if value is None:
            logger.debug("%s is not provided in the request", key)
            continue
        value.to_datetime()
        assert isinstance(value.start, datetime) and isinstance(value.end, datetime)
        if value.start >= value.end:
            logger.warning("%s start time is later than end time", key)
            raise HTTPException(
                status_code=400, detail=f"{key}의 시작 시간이 종료 시간보다 늦습니다."
            )
        if value.start < get_datetime_by_string(
            "00:00"
        ) or value.end > get_datetime_by_string("23:59"):
            logger.warning("%s time is out of valid range", key)
            raise HTTPException(
                status_code=400, detail=f"{key}의 시간이 올바르지 않습니다."
            )

        value.to_string()
        # OperatingHours 객체 생성 후 리스트에 추가
        operating_hours_entries.append(
            OperatingHours(
                type=key,
                start_time=value.start,
                end_time=value.end,
                submission_id=new_submission.id,  # ForeignKey 연결
            )
        )
        logger.debug(
            "Operating hour %s added for submission id %s", key, new_submission.id
        )

    # 모든 운영 시간 정보를 DB에 추가
    db.add_all(operating_hours_entries)
    await db.commit()
    logger.info("All operating hours added for submission id %s", new_submission.id)

    assert isinstance(new_submission.id, int)
    response_data = SubmissionResponse(request_id=new_submission.id)
    logger.info("Submission process completed for request id %s", new_submission.id)

    return BaseSchema[SubmissionResponse](data=response_data)


@router.delete("/requests/{submission_id}", status_code=204)
async def restaurant_submit_delete(
    submission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """DELETE /restaurants/requests/{submission_id} 엔드포인트"""
    logger.info(
        "Delete request received for submission_id: %s by user: %s",
        submission_id,
        current_user.id,
    )

    result = await db.execute(
        select(RestaurantSubmission).filter(RestaurantSubmission.id == submission_id)
    )
    submission = result.scalars().first()
    if not submission:
        logger.warning("Submission with id %s not found", submission_id)
        raise HTTPException(
            status_code=404, detail="해당 제출 요청이 존재하지 않습니다."
        )
    if submission.submitter != current_user.id:
        logger.warning(
            "User %s does not have permission to delete submission with id %s",
            current_user.id,
            submission_id,
        )
        raise HTTPException(
            status_code=403, detail="해당 제출 요청을 삭제할 권한이 없습니다."
        )

    await db.delete(submission)
    await db.commit()
