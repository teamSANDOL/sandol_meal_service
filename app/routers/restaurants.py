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

from datetime import datetime, timezone
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_pagination import Params, add_pagination, paginate
from sqlalchemy import case, delete, false, insert, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from httpx import AsyncClient

from app.config import logger, Config
from app.models.restaurants import (
    OperatingHours,
    Restaurant,
    RestaurantManagerApplication,
    RestaurantSubmission,
    active_restaurant_clause,
)
from app.models.associations import restaurant_manager_association
from app.models.user import User
from app.schemas.base import BaseSchema
from app.schemas.pagination import CustomPage
from app.schemas.restaurants import (
    ApproverResponse,
    EstablishmentType,
    ESTABLISHMENT_TYPE_DESCRIPTION,
    RestaurantCreateRequest,
    RestaurantRequest,
    RestaurantResponse,
    SubmissionResponse,
    TimeRange,
    RejectRestaurantRequest,
    RestaurantManagerRequest,
    RestaurantManagerResponse,
    RestaurantManagerApplicationCreateResponse,
    RestaurantManagerApplicationResponse,
    RestaurantManagerApprovalResponse,
    RestaurantSubmission as RestaurantSubmissionSchema,
    RestaurantUpdateRequest,
    UserProfileResponse,
)
from app.schemas.users import AdminUserSchema
from app.services.user_service import get_keycloak_user_profile
from app.utils.db import (
    get_admin_user,
    get_current_user,
    get_db,
    check_admin_user,
    get_or_create_user,
    resolve_user_ids,
)
from app.utils.restaurants import (
    build_location_schema,
    build_operating_hours_entries,
    build_restaurant_model,
    build_restaurant_schema,
    fetch_owner_user_id,
    fetch_operating_hours_dict,
    fetch_restaurant_submission,
    get_restaurant_or_404,
    get_restaurant_with_permission,
    get_submission_or_404,
    get_submission_with_permission,
    replace_restaurant_operating_hours,
)
from app.utils.http import get_async_client

router = APIRouter(prefix="/restaurants", tags=["Restaurant"])


async def _ensure_restaurant_owner_or_admin(
    restaurant: Restaurant,
    current_user: User,
) -> None:
    """식당 owner 또는 admin 권한을 확인합니다."""
    if restaurant.owner == current_user.id:
        return
    admin_user = await check_admin_user(current_user)
    if admin_user.is_admin:
        return
    raise HTTPException(
        status_code=Config.HttpStatus.FORBIDDEN,
        detail="해당 식당 manager 신청을 처리할 권한이 없습니다.",
    )


async def _build_manager_application_response(
    application: RestaurantManagerApplication,
    db: AsyncSession,
) -> RestaurantManagerApplicationResponse:
    """Manager 신청 ORM 객체를 응답 스키마로 변환합니다."""
    applicant = await db.get(User, application.applicant)
    if applicant is None:
        raise HTTPException(
            status_code=Config.HttpStatus.NOT_FOUND,
            detail="신청 사용자를 찾을 수 없습니다.",
        )
    profile = await get_keycloak_user_profile(applicant.user_id)
    display_name = profile.get("display_name") or applicant.user_id
    return RestaurantManagerApplicationResponse(
        id=application.id,
        restaurant_id=application.restaurant_id,
        applicant=application.applicant,
        applicant_user_id=applicant.user_id,
        applicant_profile=UserProfileResponse(
            user_id=applicant.user_id,
            display_name=display_name,
            username=profile.get("username"),
            email=profile.get("email"),
        ),
        status=cast(
            Literal["pending", "approved", "rejected"],
            application.status,
        ),
        submitted_time=application.submitted_time,
        reviewer=application.reviewer,
        reviewed_time=application.reviewed_time,
        rejection_message=application.rejection_message,
    )


@router.get("/requests", response_model=CustomPage[RestaurantSubmissionSchema])
async def restaurant_submit_get_requests(
    db: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[Params, Depends()],
    client: Annotated[AsyncClient, Depends(get_async_client)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """모든 식당 등록 요청을 페이징하여 조회합니다.

    사용자는 자신의 등록 요청을 조회할 수 있으며,
    관리자는 모든 등록 요청을 조회할 수 있습니다.

    Args:
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        params (Params): 페이징 처리를 위한 FastAPI Pagination 객체입니다.
        current_user (User): 요청을 보낸 현재 사용자 객체입니다.
        client (AsyncClient): 비동기 HTTP 클라이언트 객체입니다.

    Returns:
        CustomPage[RestaurantSubmissionSchema]: 등록 요청 데이터 목록을 포함한 페이징된 응답 객체입니다.
    """
    logger.info("Get requests received by user: %s", current_user.id)

    # 요청자가 관리자인 경우 모든 요청 조회
    admin_user: AdminUserSchema = await check_admin_user(current_user)
    if admin_user.is_admin:
        result = await db.execute(select(RestaurantSubmission))
        submissions = result.scalars().all()
    else:
        # 요청자가 일반 사용자일 경우 자신의 요청만 조회
        result = await db.execute(
            select(RestaurantSubmission).filter(
                RestaurantSubmission.submitter == current_user.id
            )
        )
        submissions = result.scalars().all()

    # 2️⃣ ORM 객체 → Pydantic 변환
    submission_schemas = [
        await fetch_restaurant_submission(submission, db) for submission in submissions
    ]

    # 예시로 client를 사용한 로깅
    logger.debug("HTTP client base URL: %s", client.base_url)

    return paginate(submission_schemas, params)


@router.post("/requests", status_code=Config.HttpStatus.CREATED)
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
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="location, opening_time 필드는 필수입니다.",
        )

    new_submission = RestaurantSubmission(
        name=request.name,
        status="pending",
        submitter=current_user.id,
        establishment_type=request.establishment_type,
        price=request.price,
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
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="서버 내부 오류 발생",
        ) from e

    return BaseSchema[SubmissionResponse](
        data=SubmissionResponse(request_id=new_submission.id)
    )


@router.post("/", status_code=Config.HttpStatus.CREATED)
async def create_restaurant(
    request: RestaurantCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_admin_user)],
):
    """관리자가 특정 owner_user_id를 가진 식당을 직접 생성합니다."""
    _ = current_user
    if request.location is None or request.opening_time is None:
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="location, opening_time 필드는 필수입니다.",
        )

    normalized_owner_user_id = request.owner_user_id.strip()
    if not normalized_owner_user_id:
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="owner_user_id는 필수입니다.",
        )

    operation_hours_dict = {
        "opening_time": request.opening_time,
        "break_time": request.break_time,
        "breakfast_time": request.breakfast_time,
        "brunch_time": request.brunch_time,
        "lunch_time": request.lunch_time,
        "dinner_time": request.dinner_time,
    }

    try:
        owner_user = await get_or_create_user(normalized_owner_user_id, db)
        new_restaurant = build_restaurant_model(request, owner_id=owner_user.id)
        db.add(new_restaurant)
        await db.flush()

        operating_hours_entries = build_operating_hours_entries(
            operation_hours_dict,
            restaurant_id=new_restaurant.id,
        )
        db.add_all(operating_hours_entries)

        await db.commit()
        await db.refresh(new_restaurant)
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as e:
        await db.rollback()
        logger.error("Restaurant 생성 중 예외 발생: %s", e)
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="서버 내부 오류 발생",
        ) from e

    operating_hours = await fetch_operating_hours_dict(db, restaurant_id=new_restaurant.id)
    return BaseSchema[RestaurantResponse](
        data=build_restaurant_schema(
            new_restaurant,
            operating_hours,
            owner_user_id=owner_user.user_id,
        )
    )


@router.post("/restaurants/{request_id}/approval")
async def restaurant_submit_approval(
    request_id: int,
    submission: Annotated[RestaurantSubmission, Depends(get_submission_or_404)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[AdminUserSchema, Depends(get_admin_user)],
):
    """식당 등록 요청을 승인합니다.

    관리자는 `pending` 상태의 식당 등록 요청을 승인하여 실제 식당 데이터로 저장할 수 있습니다.
    승인된 식당은 `restaurants` 테이블에 저장되며, 요청의 운영시간도 함께 복사됩니다.

    Args:
        request_id (int): 승인할 식당 등록 요청의 고유 ID입니다.
        submission (RestaurantSubmission): 승인할 제출 요청 객체입니다.
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        current_user (AdminUserSchema): 현재 요청을 보낸 관리자 사용자 객체입니다.

    Returns:
        BaseSchema[ApproverResponse]: 승인된 식당 정보를 포함한 응답 객체입니다.

    Raises:
        HTTPException(400): 요청이 이미 승인되었거나 거절된 경우 발생합니다.
        HTTPException(404): 해당 요청을 찾을 수 없는 경우 발생합니다.
        HTTPException(500): 서버 내부 오류로 인해 승인 처리가 실패한 경우 발생합니다.
    """
    if submission.status != "pending":
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="해당 제출 요청은 이미 처리되었습니다.",
        )

    submission.status = "approved"
    submission.reviewer = current_user.id

    new_restaurant = Restaurant(
        name=submission.name,
        owner=submission.submitter,
        establishment_type=submission.establishment_type,
        price=submission.price,
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
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="서버 내부 오류 발생",
        ) from e

    return BaseSchema[ApproverResponse](
        data=ApproverResponse(restaurant_id=new_restaurant.id)
    )


@router.post(
    "/restaurants/{request_id}/rejection", status_code=Config.HttpStatus.NO_CONTENT
)
async def restaurant_submit_rejection(
    request_id: int,
    submission: Annotated[RestaurantSubmission, Depends(get_submission_or_404)],
    request_body: RejectRestaurantRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[AdminUserSchema, Depends(get_admin_user)],
):
    """식당 등록 요청을 거절합니다.

    관리자는 `pending` 상태의 식당 등록 요청을 거절할 수 있습니다.
    거절된 요청은 `rejected` 상태로 변경되며, 거절 사유(`rejection_message`)를 입력해야 합니다.

    Args:
        request_id (int): 거절할 식당 등록 요청의 고유 ID입니다.
        submission (RestaurantSubmission): 거절할 제출 요청 객체입니다.
        request_body (RejectRestaurantRequest): 거절 사유를 포함한 요청 객체입니다.
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        current_user (UserSchema): 현재 요청을 보낸 관리자 사용자 객체입니다.

    Raises:
        HTTPException(400): 요청이 이미 승인되었거나 거절된 경우 발생합니다.
        HTTPException(404): 해당 요청을 찾을 수 없는 경우 발생합니다.
        HTTPException(400): 거절 사유가 입력되지 않은 경우 발생합니다.
        HTTPException(500): 서버 내부 오류로 인해 거절 처리가 실패한 경우 발생합니다.
    """
    if submission.status != "pending":
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="해당 제출 요청은 이미 처리되었습니다.",
        )

    rejection_message = request_body.message
    if not rejection_message:
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="거부 사유는 필수 입력 사항입니다.",
        )

    submission.status = "rejected"
    submission.reviewer = current_user.id
    submission.rejection_message = rejection_message

    try:
        db.add(submission)
        await db.commit()

    except Exception as e:
        await db.rollback()
        logger.error("Approval 처리 중 예외 발생: %s", e)
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="서버 내부 오류 발생",
        ) from e


@router.get("/requests/{request_id}")
async def restaurant_submit_get(
    request_id: int,
    submission: Annotated[
        RestaurantSubmission, Depends(get_submission_with_permission)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """특정 식당 등록 요청을 조회합니다.

    사용자는 `request_id`를 이용하여 해당 요청의 상태 및 세부 정보를 확인할 수 있습니다.

    Args:
        request_id (int): 조회할 식당 등록 요청의 고유 ID입니다.
        submission (RestaurantSubmission): 조회된 제출 요청 객체입니다.
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

    response_data = await fetch_restaurant_submission(submission, db)

    return BaseSchema[RestaurantSubmissionSchema](data=response_data)


@router.delete("/requests/{request_id}", status_code=Config.HttpStatus.NO_CONTENT)
async def restaurant_submit_delete(
    request_id: int,
    submission: Annotated[
        RestaurantSubmission, Depends(get_submission_with_permission)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """특정 식당 등록 요청을 삭제합니다.

    요청자가 자신의 `pending` 상태인 등록 요청을 삭제할 수 있습니다.
    승인되거나 거절된 요청은 삭제할 수 없습니다.

    Args:
        request_id (int): 삭제할 식당 등록 요청의 고유 ID입니다.
        submission (RestaurantSubmission): 조회된 제출 요청 객체입니다.
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

    await db.delete(submission)
    await db.commit()
    logger.info("Submission with id %s deleted successfully", request_id)


@router.post(
    "/{restaurant_id}/manager-requests",
    status_code=Config.HttpStatus.CREATED,
    response_model=BaseSchema[RestaurantManagerApplicationCreateResponse],
)
async def create_restaurant_manager_application(
    restaurant_id: int,
    restaurant: Annotated[Restaurant, Depends(get_restaurant_or_404)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """일반 사용자가 특정 식당 manager 등록을 신청합니다."""
    if restaurant.owner == current_user.id:
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="식당 owner는 manager 신청을 할 수 없습니다.",
        )

    manager_result = await db.execute(
        select(restaurant_manager_association.c.user_id).where(
            restaurant_manager_association.c.restaurant_id == restaurant_id,
            restaurant_manager_association.c.user_id == current_user.id,
        )
    )
    if manager_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=Config.HttpStatus.CONFLICT,
            detail="이미 등록된 manager입니다.",
        )

    pending_result = await db.execute(
        select(RestaurantManagerApplication.id).where(
            RestaurantManagerApplication.restaurant_id == restaurant_id,
            RestaurantManagerApplication.applicant == current_user.id,
            RestaurantManagerApplication.status == "pending",
        )
    )
    if pending_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=Config.HttpStatus.CONFLICT,
            detail="이미 처리 대기 중인 manager 신청이 있습니다.",
        )

    application = RestaurantManagerApplication(
        restaurant_id=restaurant.id,
        applicant=current_user.id,
        status="pending",
    )
    try:
        db.add(application)
        await db.commit()
        await db.refresh(application)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=Config.HttpStatus.CONFLICT,
            detail="이미 처리 대기 중인 manager 신청이 있습니다.",
        ) from exc
    except Exception as e:
        await db.rollback()
        logger.error("Restaurant manager 신청 생성 중 예외 발생: %s", e)
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="서버 내부 오류 발생",
        ) from e

    return BaseSchema[RestaurantManagerApplicationCreateResponse](
        data=RestaurantManagerApplicationCreateResponse(
            request_id=application.id,
            restaurant_id=restaurant.id,
        )
    )


@router.get(
    "/{restaurant_id}/manager-requests",
    response_model=BaseSchema[list[RestaurantManagerApplicationResponse]],
)
async def get_restaurant_manager_applications(
    restaurant_id: int,
    restaurant: Annotated[Restaurant, Depends(get_restaurant_or_404)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    status: str = Query("pending", description="신청 상태 필터"),
):
    """식당 owner 또는 admin이 manager 신청 목록을 조회합니다."""
    await _ensure_restaurant_owner_or_admin(restaurant, current_user)
    if status not in {"pending", "approved", "rejected", "all"}:
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="status 값이 올바르지 않습니다.",
        )

    stmt = select(RestaurantManagerApplication).where(
        RestaurantManagerApplication.restaurant_id == restaurant_id
    )
    if status != "all":
        stmt = stmt.where(RestaurantManagerApplication.status == status)
    stmt = stmt.order_by(RestaurantManagerApplication.submitted_time.desc())
    result = await db.execute(stmt)
    applications = result.scalars().all()
    response_data = [
        await _build_manager_application_response(application, db)
        for application in applications
    ]
    return BaseSchema[list[RestaurantManagerApplicationResponse]](data=response_data)


@router.post(
    "/{restaurant_id}/manager-requests/{request_id}/approval",
    response_model=BaseSchema[RestaurantManagerApprovalResponse],
)
async def approve_restaurant_manager_application(
    restaurant_id: int,
    request_id: int,
    restaurant: Annotated[Restaurant, Depends(get_restaurant_or_404)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """식당 owner 또는 admin이 manager 신청을 승인합니다."""
    await _ensure_restaurant_owner_or_admin(restaurant, current_user)
    result = await db.execute(
        select(RestaurantManagerApplication).where(
            RestaurantManagerApplication.id == request_id,
            RestaurantManagerApplication.restaurant_id == restaurant_id,
        )
    )
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(
            status_code=Config.HttpStatus.NOT_FOUND,
            detail="manager 신청을 찾을 수 없습니다.",
        )
    if application.status != "pending":
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="이미 처리된 manager 신청입니다.",
        )

    applicant = await db.get(User, application.applicant)
    if applicant is None:
        raise HTTPException(
            status_code=Config.HttpStatus.NOT_FOUND,
            detail="신청 사용자를 찾을 수 없습니다.",
        )

    existing_result = await db.execute(
        select(restaurant_manager_association.c.user_id).where(
            restaurant_manager_association.c.restaurant_id == restaurant_id,
            restaurant_manager_association.c.user_id == applicant.id,
        )
    )
    try:
        if existing_result.scalar_one_or_none() is None:
            await db.execute(
                insert(restaurant_manager_association).values(
                    restaurant_id=restaurant_id,
                    user_id=applicant.id,
                )
            )
        application.status = "approved"
        application.reviewer = current_user.id
        application.reviewed_time = datetime.now(timezone.utc)
        db.add(application)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        application.status = "approved"
        application.reviewer = current_user.id
        application.reviewed_time = datetime.now(timezone.utc)
        db.add(application)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("Restaurant manager 신청 승인 중 예외 발생: %s", e)
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="서버 내부 오류 발생",
        ) from e

    return BaseSchema[RestaurantManagerApprovalResponse](
        data=RestaurantManagerApprovalResponse(
            restaurant_id=restaurant_id,
            user_id=applicant.user_id,
            request_id=application.id,
        )
    )


@router.get(
    "/{restaurant_id}/managers",
    response_model=BaseSchema[list[RestaurantManagerResponse]],
)
async def get_restaurant_managers(
    restaurant_id: int,
    restaurant: Annotated[Restaurant, Depends(get_restaurant_or_404)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_admin_user)],
):
    """관리자가 특정 식당의 manager 목록을 조회합니다."""
    _ = (restaurant, current_user)
    result = await db.execute(
        select(User.user_id)
        .select_from(restaurant_manager_association)
        .join(User, restaurant_manager_association.c.user_id == User.id)
        .where(restaurant_manager_association.c.restaurant_id == restaurant_id)
        .order_by(User.user_id.asc())
    )
    managers = [
        RestaurantManagerResponse(restaurant_id=restaurant_id, user_id=user_id)
        for user_id in result.scalars().all()
    ]
    return BaseSchema[list[RestaurantManagerResponse]](data=managers)


@router.post(
    "/{restaurant_id}/managers",
    status_code=Config.HttpStatus.CREATED,
    response_model=BaseSchema[RestaurantManagerResponse],
)
async def add_restaurant_manager(
    restaurant_id: int,
    request: RestaurantManagerRequest,
    restaurant: Annotated[Restaurant, Depends(get_restaurant_or_404)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_admin_user)],
):
    """관리자가 특정 식당에 manager를 등록합니다."""
    _ = (restaurant, current_user)
    manager_user_id = request.user_id.strip()
    if not manager_user_id:
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="manager user_id는 필수입니다.",
        )

    try:
        manager = await get_or_create_user(manager_user_id, db)
        existing_result = await db.execute(
            select(restaurant_manager_association.c.user_id).where(
                restaurant_manager_association.c.restaurant_id == restaurant_id,
                restaurant_manager_association.c.user_id == manager.id,
            )
        )
        if existing_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=Config.HttpStatus.CONFLICT,
                detail="이미 등록된 manager입니다.",
            )

        await db.execute(
            insert(restaurant_manager_association).values(
                restaurant_id=restaurant_id,
                user_id=manager.id,
            )
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=Config.HttpStatus.CONFLICT,
            detail="이미 등록된 manager입니다.",
        ) from exc
    except Exception as e:
        await db.rollback()
        logger.error("Restaurant manager 등록 중 예외 발생: %s", e)
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="서버 내부 오류 발생",
        ) from e

    return BaseSchema[RestaurantManagerResponse](
        data=RestaurantManagerResponse(
            restaurant_id=restaurant_id,
            user_id=manager.user_id,
        )
    )


@router.delete(
    "/{restaurant_id}/managers/{user_id}",
    status_code=Config.HttpStatus.NO_CONTENT,
)
async def remove_restaurant_manager(
    restaurant_id: int,
    user_id: str,
    restaurant: Annotated[Restaurant, Depends(get_restaurant_or_404)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_admin_user)],
):
    """관리자가 특정 식당의 manager를 해제합니다."""
    _ = (restaurant, current_user)
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="manager user_id는 필수입니다.",
        )

    manager_result = await db.execute(
        select(User).where(User.user_id == normalized_user_id)
    )
    manager = manager_result.scalar_one_or_none()
    if manager is None:
        raise HTTPException(
            status_code=Config.HttpStatus.NOT_FOUND,
            detail="등록된 manager 사용자를 찾을 수 없습니다.",
        )

    existing_result = await db.execute(
        select(restaurant_manager_association.c.user_id).where(
            restaurant_manager_association.c.restaurant_id == restaurant_id,
            restaurant_manager_association.c.user_id == manager.id,
        )
    )
    if existing_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=Config.HttpStatus.NOT_FOUND,
            detail="해당 식당에 등록된 manager가 아닙니다.",
        )

    await db.execute(
        delete(restaurant_manager_association).where(
            restaurant_manager_association.c.restaurant_id == restaurant_id,
            restaurant_manager_association.c.user_id == manager.id,
        )
    )
    await db.commit()


@router.get("/{restaurant_id}")
async def get_restaurant(
    restaurant_id: int,
    restaurant: Annotated[Restaurant, Depends(get_restaurant_or_404)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """특정 식당 정보를 조회합니다.

    `restaurant_id`를 이용하여 해당 식당의 기본 정보와 운영 시간을 조회합니다.

    Args:
        restaurant_id (int): 조회할 식당의 고유 ID입니다.
        restaurant (Restaurant): 조회된 식당 객체입니다.
        db (AsyncSession): 비동기 DB 세션 객체입니다.

    Returns:
        BaseSchema[RestaurantResponse]: 조회된 식당 정보를 포함한 응답 객체입니다.

    Raises:
        HTTPException(404): 해당 식당을 찾을 수 없는 경우 발생합니다.
    """
    operating_hours_dict = await fetch_operating_hours_dict(
        db, restaurant_id=restaurant_id
    )
    owner_user_id = await fetch_owner_user_id(db, restaurant.owner)
    logger.debug(
        "Found %s operating hours for restaurant id %s",
        len(operating_hours_dict),
        restaurant_id,
    )

    response_data = RestaurantResponse(
        id=restaurant.id,
        name=restaurant.name,
        owner=restaurant.owner,
        owner_user_id=owner_user_id,
        establishment_type=cast(EstablishmentType, restaurant.establishment_type),
        price=restaurant.price,
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


@router.patch("/{restaurant_id}")
async def update_restaurant(
    restaurant_id: int,
    request: RestaurantUpdateRequest,
    restaurant: Annotated[Restaurant, Depends(get_restaurant_or_404)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_admin_user)],
):
    """관리자가 저장된 식당 정보를 수정합니다."""
    _ = (restaurant_id, current_user)
    if request.location is None or request.opening_time is None:
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail="location, opening_time 필드는 필수입니다.",
        )

    location = request.location
    operation_hours_dict = {
        "opening_time": request.opening_time,
        "break_time": request.break_time,
        "breakfast_time": request.breakfast_time,
        "brunch_time": request.brunch_time,
        "lunch_time": request.lunch_time,
        "dinner_time": request.dinner_time,
    }

    try:
        owner_user_id = request.owner_user_id.strip() if request.owner_user_id else None
        if owner_user_id is not None and not owner_user_id:
            raise HTTPException(
                status_code=Config.HttpStatus.BAD_REQUEST,
                detail="owner_user_id는 비어 있을 수 없습니다.",
            )

        resolved_owner = None
        if owner_user_id is not None:
            resolved_owner = await get_or_create_user(owner_user_id, db)
        else:
            resolved_owner = await db.get(User, restaurant.owner)
            if resolved_owner is None:
                raise HTTPException(
                    status_code=Config.HttpStatus.NOT_FOUND,
                    detail="기존 owner 사용자를 찾을 수 없습니다.",
                )

        build_restaurant_model(request, owner_id=resolved_owner.id)

        restaurant.name = request.name
        restaurant.owner = resolved_owner.id
        restaurant.establishment_type = request.establishment_type
        restaurant.price = request.price
        restaurant.is_campus = location.is_campus
        restaurant.building_name = location.building
        restaurant.naver_map_link = (location.map_links or {}).get("naver")
        restaurant.kakao_map_link = (location.map_links or {}).get("kakao")
        restaurant.latitude = location.latitude
        restaurant.longitude = location.longitude

        await replace_restaurant_operating_hours(
            db,
            restaurant_id=restaurant.id,
            operation_hours_dict=operation_hours_dict,
        )

        db.add(restaurant)
        await db.commit()
        await db.refresh(restaurant)
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=Config.HttpStatus.BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as e:
        await db.rollback()
        logger.error("Restaurant 수정 중 예외 발생: %s", e)
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="서버 내부 오류 발생",
        ) from e

    operating_hours = await fetch_operating_hours_dict(db, restaurant_id=restaurant.id)
    return BaseSchema[RestaurantResponse](
        data=build_restaurant_schema(
            restaurant,
            operating_hours,
            owner_user_id=resolved_owner.user_id,
        )
    )


@router.delete("/{restaurant_id}", status_code=Config.HttpStatus.NO_CONTENT)
async def delete_restaurant(
    restaurant_id: int,
    restaurant: Annotated[Restaurant, Depends(get_restaurant_with_permission)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """특정 식당을 삭제합니다.

    식당 소유자는 본인이 등록한 식당을 삭제할 수 있습니다.
    식당 삭제 시 운영시간 정보도 함께 삭제됩니다.

    Args:
        restaurant_id (int): 삭제할 식당의 고유 ID입니다.
        restaurant (Restaurant): 조회된 식당 객체입니다.
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        current_user (User): 요청을 보낸 현재 사용자 객체입니다.

    Raises:
        HTTPException(403): 해당 식당을 삭제할 권한이 없는 경우 발생합니다.
        HTTPException(404): 해당 식당을 찾을 수 없는 경우 발생합니다.
        HTTPException(500): 서버 내부 오류로 인해 삭제 처리가 실패한 경우 발생합니다.
    """
    current_user_id = current_user.id
    logger.info(
        "Delete request received for restaurant_id: %s by user: %s",
        restaurant_id,
        current_user_id,
    )

    try:
        # 운영 시간 한 번에 삭제
        await db.execute(
            delete(OperatingHours).where(OperatingHours.restaurant_id == restaurant_id)
        )

        # 기존 식단은 보존하되 식당과 식단이 일반 조회에 노출되지 않도록 처리
        restaurant.soft_delete()

        # 트랜잭션 커밋
        await db.commit()

        logger.info(
            "Restaurant %s deleted successfully by user %s",
            restaurant_id,
            current_user_id,
        )

    except IntegrityError as e:
        await db.rollback()
        logger.warning(
            "Restaurant %s could not be deleted by user %s because related data exists: %s",
            restaurant_id,
            current_user_id,
            e,
        )
        raise HTTPException(
            status_code=Config.HttpStatus.CONFLICT,
            detail="연결된 데이터가 있는 식당은 삭제할 수 없습니다.",
        ) from e
    except Exception as e:
        await db.rollback()
        logger.error(
            "Error occurred while deleting restaurant %s by user %s: %s",
            restaurant_id,
            current_user_id,
            e,
        )
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="서버 내부 오류 발생",
        ) from e


@router.get("/", response_model=CustomPage[RestaurantResponse])
async def get_restaurants(  # noqa: PLR0913
    db: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[Params, Depends()],
    owner_user_id: str = Query(None, description="식당 소유자 user_id"),
    manager_user_id: str = Query(None, description="식당 관리자 user_id"),
    name: str = Query(None, description="식당 이름 (부분 일치)"),
    establishment_type: Annotated[
        EstablishmentType | None,
        Query(description=ESTABLISHMENT_TYPE_DESCRIPTION),
    ] = None,
    is_campus: bool = Query(None, description="캠퍼스 내 식당 여부(true|false)"),
):
    """모든 식당 데이터를 페이징하여 조회합니다.

    Args:
        db (AsyncSession): 비동기 DB 세션 객체입니다.
        params (Params): 페이징 처리를 위한 FastAPI Pagination 객체입니다.
        owner_user_id (str, optional): 소유자 user_id로 필터링
        manager_user_id (str, optional): 관리자 user_id로 필터링
        name (str, optional): 식당 이름(부분 일치)으로 필터링
        establishment_type (str, optional): 식당 유형(student|fixed_menu_restaurant|fixed_korean_buffet|variable_korean_buffet)
        is_campus (bool, optional): 캠퍼스 내 식당 여부

    Returns:
        CustomPage[RestaurantResponse]: 식당 데이터 목록을 포함한 페이징된 응답 객체입니다.
    """
    owner_filter_requested = owner_user_id is not None
    manager_filter_requested = manager_user_id is not None

    owner_id, manager_id = await resolve_user_ids(
        db,
        owner_user_id,
        manager_user_id,
    )
    stmt = select(Restaurant).where(active_restaurant_clause())

    user_filters = []
    if owner_filter_requested and owner_id is not None:
        user_filters.append(Restaurant.owner == owner_id)
    if manager_filter_requested and manager_id is not None:
        user_filters.append(Restaurant.managers.any(id=manager_id))

    if owner_filter_requested or manager_filter_requested:
        if user_filters:
            stmt = stmt.where(or_(*user_filters))
        else:
            stmt = stmt.where(false())
    if name:
        stmt = stmt.where(Restaurant.name.contains(name))
        stmt = stmt.order_by(
            case((Restaurant.name == name, 0), else_=1), Restaurant.name.asc()
        )
    if establishment_type:
        stmt = stmt.where(Restaurant.establishment_type == establishment_type)
    if is_campus is not None:
        stmt = stmt.where(Restaurant.is_campus == is_campus)

    result = await db.execute(stmt)
    restaurants = result.scalars().all()

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
            owner_user_id=await fetch_owner_user_id(db, restaurant.owner),
            establishment_type=cast(EstablishmentType, restaurant.establishment_type),
            price=restaurant.price,
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
    logger.info("Total restaurants found: %d", len(restaurant_schemas))

    return paginate(restaurant_schemas, params)


add_pagination(router)
