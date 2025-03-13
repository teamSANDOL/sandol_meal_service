"""식당 관리 API 모듈

이 모듈은 FastAPI를 기반으로 식당 관련 CRUD API를 제공합니다.
사용자는 식당을 등록, 승인, 거절, 조회, 삭제할 수 있으며,
페이징을 지원하여 여러 식당을 효율적으로 조회할 수 있습니다.

API 목록:
    - `POST /restaurants/requests`: 새로운 식당 등록 요청을 생성합니다.
    - `POST /restaurants/{request_id}/approval`: 식당 등록 요청을 승인합니다.
    - `POST /restaurants/{request_id}/rejection`: 식당 등록 요청을 거절합니다.
    - `GET /restaurants/requests/{request_id}`: 특정 식당 등록 요청을 조회합니다.
    - `DELETE /restaurants/requests/{request_id}`: 특정 식당 등록 요청을 삭제합니다.
    - `GET /restaurants/{restaurant_id}`: 특정 식당 정보를 조회합니다.
    - `DELETE /restaurants/{restaurant_id}`: 특정 식당을 삭제합니다.
    - `GET /restaurants/`: 모든 식당 데이터를 페이징하여 조회합니다.

이 모듈은 다음과 같은 주요 유틸리티 함수를 활용합니다:
    - `build_location_schema`: 위치 정보를 변환하는 함수
    - `build_operating_hours_entries`: 운영시간 데이터를 변환하는 함수
    - `fetch_operating_hours_dict`: 운영시간 데이터를 조회하는 함수
    - `get_restaurant_or_404`: 특정 식당 정보를 조회하고 없을 경우 404 오류를 반환하는 함수
    - `get_submission_or_404`: 특정 식당 등록 요청을 조회하고 없을 경우 404 오류를 반환하는 함수

모든 API는 비동기적으로 동작하며, SQLAlchemy의 `AsyncSession`을 활용하여 데이터베이스와 통신합니다.
"""


from fastapi import APIRouter, Depends, HTTPException
from fastapi_pagination import Params, add_pagination, paginate
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import logger
from app.models.restaurants import (
    OperatingHours,
    Restaurant,
    RestaurantSubmission,
)
from app.models.user import User
from app.schemas.base import BaseSchema
from app.schemas.pagination import CustomPage
from app.schemas.restaurants import (
    ApproverResponse,
    RestaurantRequest,
    RestaurantResponse,
    SubmissionResponse,
    TimeRange,
    UserSchema,
    RejectRestaurantRequest,
)
from app.schemas.restaurants import RestaurantSubmission as RestaurantSubmissionSchema
from app.utils.db import get_admin_user, get_current_user, get_db
from app.utils.restaurants import (
    build_location_schema,
    build_operating_hours_entries,
    fetch_operating_hours_dict,
    get_restaurant_or_404,
    get_submission_or_404,
)
from typing import Annotated

router = APIRouter(prefix="/restaurants")


@router.post("/requests")
async def restaurant_submit_request(
    request: RestaurantRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """새로운 식당 등록 요청을 생성합니다.

    사용자는 식당 정보를 입력하여 등록 요청을 제출할 수 있으며,
    관리자가 승인하기 전까지 `pending` 상태로 유지됩니다.
    등록 요청에는 기본적인 식당 정보(이름, 위치, 운영시간 등)가 포함됩니다.

    Args:
        request (RestaurantRequest): 새로 등록할 식당 정보를 포함한 요청 객체입니다.
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        current_user (User): 요청을 보낸 현재 사용자 객체입니다.

    Returns:
        BaseSchema[SubmissionResponse]: 제출된 요청 정보를 포함한 응답 객체입니다.

    Raises:
        HTTPException(400): `location` 또는 `opening_time`이 누락된 경우 발생합니다.
        HTTPException(500): 서버 내부 오류로 인해 요청 처리가 실패한 경우 발생합니다.
    """
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
        raise HTTPException(status_code=500, detail="서버 내부 오류 발생") from e

    return BaseSchema[SubmissionResponse](
        data=SubmissionResponse(request_id=new_submission.id)
    )


@router.post("/restaurants/{request_id}/approval")
async def restaurant_submit_approval(
    request_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserSchema, Depends(get_admin_user)],
):
    """식당 등록 요청을 승인합니다.

    관리자는 `pending` 상태의 식당 등록 요청을 승인하여 실제 식당 데이터로 저장할 수 있습니다.
    승인된 식당은 `restaurants` 테이블에 저장되며, 요청의 운영시간도 함께 복사됩니다.

    Args:
        request_id (int): 승인할 식당 등록 요청의 고유 ID입니다.
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        current_user (UserSchema): 현재 요청을 보낸 관리자 사용자 객체입니다.

    Returns:
        BaseSchema[ApproverResponse]: 승인된 식당 정보를 포함한 응답 객체입니다.

    Raises:
        HTTPException(400): 요청이 이미 승인되었거나 거절된 경우 발생합니다.
        HTTPException(404): 해당 요청을 찾을 수 없는 경우 발생합니다.
        HTTPException(500): 서버 내부 오류로 인해 승인 처리가 실패한 경우 발생합니다.
    """
    submission: RestaurantSubmission = await get_submission_or_404(db, request_id)
    if submission.status != "pending":
        raise HTTPException(
            status_code=400, detail="해당 제출 요청은 이미 처리되었습니다."
        )

    submission.status = "approved"
    submission.reviewer = current_user.id

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
        raise HTTPException(status_code=500, detail="서버 내부 오류 발생") from e

    return BaseSchema[ApproverResponse](
        data=ApproverResponse(restaurant_id=new_restaurant.id)
    )


@router.post("/restaurants/{request_id}/rejection", status_code=204)
async def restaurant_submit_rejection(
    request_id: int,
    request_body: RejectRestaurantRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[UserSchema, Depends(get_admin_user)],
):
    """식당 등록 요청을 거절합니다.

    관리자는 `pending` 상태의 식당 등록 요청을 거절할 수 있습니다.
    거절된 요청은 `rejected` 상태로 변경되며, 거절 사유(`rejection_message`)를 입력해야 합니다.

    Args:
        request_id (int): 거절할 식당 등록 요청의 고유 ID입니다.
        request_body (RejectRestaurantRequest): 거절 사유를 포함한 요청 객체입니다.
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        current_user (UserSchema): 현재 요청을 보낸 관리자 사용자 객체입니다.

    Raises:
        HTTPException(400): 요청이 이미 승인되었거나 거절된 경우 발생합니다.
        HTTPException(404): 해당 요청을 찾을 수 없는 경우 발생합니다.
        HTTPException(400): 거절 사유가 입력되지 않은 경우 발생합니다.
        HTTPException(500): 서버 내부 오류로 인해 거절 처리가 실패한 경우 발생합니다.
    """
    submission: RestaurantSubmission = await get_submission_or_404(db, request_id)
    if submission.status != "pending":
        raise HTTPException(
            status_code=400, detail="해당 제출 요청은 이미 처리되었습니다."
        )

    rejection_message = request_body.message
    if not rejection_message:
        raise HTTPException(status_code=400, detail="거부 사유는 필수 입력 사항입니다.")

    submission.status = "rejected"
    submission.reviewer = current_user.id
    submission.rejection_message = rejection_message

    try:
        db.add(submission)
        await db.commit()

    except Exception as e:
        await db.rollback()
        logger.error("Approval 처리 중 예외 발생: %s", e)
        raise HTTPException(status_code=500, detail="서버 내부 오류 발생") from e


@router.get("/requests/{request_id}")
async def restaurant_submit_get(
    request_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """특정 식당 등록 요청을 조회합니다.

    사용자는 `request_id`를 이용하여 해당 요청의 상태 및 세부 정보를 확인할 수 있습니다.

    Args:
        request_id (int): 조회할 식당 등록 요청의 고유 ID입니다.
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        current_user (User): 요청을 보낸 현재 사용자 객체입니다.

    Returns:
        BaseSchema[RestaurantSubmissionSchema]: 요청된 식당 등록 정보를 포함한 응답 객체입니다.

    Raises:
        HTTPException(404): 해당 요청을 찾을 수 없는 경우 발생합니다.
    """
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
        reviewer=submission.reviewer,
        reviewed_time=submission.reviewed_time,
        rejection_message=submission.rejection_message,
    )

    return BaseSchema[RestaurantSubmissionSchema](data=response_data)


@router.delete("/requests/{request_id}", status_code=204)
async def restaurant_submit_delete(
    request_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """특정 식당 등록 요청을 삭제합니다.

    요청자가 자신의 `pending` 상태인 등록 요청을 삭제할 수 있습니다.
    승인되거나 거절된 요청은 삭제할 수 없습니다.

    Args:
        request_id (int): 삭제할 식당 등록 요청의 고유 ID입니다.
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        current_user (User): 요청을 보낸 현재 사용자 객체입니다.

    Raises:
        HTTPException(403): 요청을 삭제할 권한이 없는 경우 발생합니다.
        HTTPException(404): 해당 요청을 찾을 수 없는 경우 발생합니다.
    """
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
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """특정 식당 정보를 조회합니다.

    `restaurant_id`를 이용하여 해당 식당의 기본 정보와 운영 시간을 조회합니다.

    Args:
        restaurant_id (int): 조회할 식당의 고유 ID입니다.
        db (AsyncSession): 비동기 DB 세션 객체입니다.

    Returns:
        BaseSchema[RestaurantResponse]: 조회된 식당 정보를 포함한 응답 객체입니다.

    Raises:
        HTTPException(404): 해당 식당을 찾을 수 없는 경우 발생합니다.
    """
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


@router.delete("/{restaurant_id}", status_code=204)
async def delete_restaurant(
    restaurant_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """특정 식당을 삭제합니다.

    식당 소유자는 본인이 등록한 식당을 삭제할 수 있습니다.
    식당 삭제 시 운영시간 정보도 함께 삭제됩니다.

    Args:
        restaurant_id (int): 삭제할 식당의 고유 ID입니다.
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        current_user (User): 요청을 보낸 현재 사용자 객체입니다.

    Raises:
        HTTPException(403): 해당 식당을 삭제할 권한이 없는 경우 발생합니다.
        HTTPException(404): 해당 식당을 찾을 수 없는 경우 발생합니다.
        HTTPException(500): 서버 내부 오류로 인해 삭제 처리가 실패한 경우 발생합니다.
    """
    logger.info(
        "Delete request received for restaurant_id: %s by user: %s",
        restaurant_id,
        current_user.id,
    )

    restaurant = await get_restaurant_or_404(db, restaurant_id)

    # 식당 삭제 권한 확인 (소유자만 가능)
    if restaurant.owner != current_user.id:
        logger.warning(
            "User %s does not have permission to delete restaurant %s",
            current_user.id,
            restaurant_id,
        )
        raise HTTPException(
            status_code=403, detail="해당 식당을 삭제할 권한이 없습니다."
        )

    try:
        # 운영 시간 한 번에 삭제
        await db.execute(
            delete(OperatingHours).where(OperatingHours.restaurant_id == restaurant_id)
        )

        # 식당 삭제
        await db.execute(delete(Restaurant).where(Restaurant.id == restaurant_id))

        # 트랜잭션 커밋
        await db.commit()

        logger.info(
            "Restaurant %s deleted successfully by user %s",
            restaurant_id,
            current_user.id,
        )

    except Exception as e:
        await db.rollback()
        logger.error(
            "Error occurred while deleting restaurant %s by user %s: %s",
            restaurant_id,
            current_user.id,
            e,
        )
        raise HTTPException(status_code=500, detail="서버 내부 오류 발생") from e


@router.get("/", response_model=CustomPage[RestaurantResponse])
async def get_restaurants(
    db: Annotated[AsyncSession, Depends(get_db)], params: Annotated[Params, Depends()]
):
    """모든 식당 데이터를 페이징하여 조회합니다.

    Args:
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        params (Params): 페이징 처리를 위한 FastAPI Pagination 객체입니다.

    Returns:
        CustomPage[RestaurantResponse]: 식당 데이터 목록을 포함한 페이징된 응답 객체입니다.
    """
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
