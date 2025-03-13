"""Restaurants 유틸리티 모듈.

이 모듈은 식당과 관련된 다양한 유틸리티 함수들을 포함하고 있습니다.
"""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.restaurants import OperatingHours, Restaurant, RestaurantSubmission
from app.schemas.restaurants import (
    Location,
    RestaurantResponse,
    TimeRange,
)
from app.utils.times import get_datetime_by_string


async def fetch_operating_hours_dict(
    db: AsyncSession,
    *,
    submission_id: int | None = None,
    restaurant_id: int | None = None,
) -> dict[str, TimeRange]:
    """submission_id나 restaurant_id를 받아 OperatingHours를 조회한 뒤, dict로 변환.

    Args:
        db (AsyncSession): 데이터베이스 세션.
        submission_id (int | None, optional): 제출 ID.
        restaurant_id (int | None, optional): 식당 ID.

    Returns:
        dict[str, TimeRange]: 운영 시간 정보를 담은 딕셔너리.
    """
    if submission_id:
        rows = await db.execute(
            select(OperatingHours).filter(OperatingHours.submission_id == submission_id)
        )
    elif restaurant_id:
        rows = await db.execute(
            select(OperatingHours).filter(OperatingHours.restaurant_id == restaurant_id)
        )
    else:
        return {}

    operating_hours = rows.scalars().all()
    return {
        oh.type: TimeRange(start=oh.start_time, end=oh.end_time)
        for oh in operating_hours
    }


def build_map_links(naver_link: str | None, kakao_link: str | None) -> dict | None:
    """네이버와 카카오 지도 링크를 딕셔너리로 생성.

    Args:
        naver_link (str | None): 네이버 지도 링크.
        kakao_link (str | None): 카카오 지도 링크.

    Returns:
        dict | None: 지도 링크를 담은 딕셔너리 또는 None.
    """
    map_links = {}
    if naver_link:
        map_links["naver"] = naver_link
    if kakao_link:
        map_links["kakao"] = kakao_link
    return map_links if map_links else None


def build_location_schema(  # noqa: PLR0913
    is_campus: bool,
    building: str | None,
    naver_link: str | None,
    kakao_link: str | None,
    lat: float | None,
    lon: float | None,
) -> Location:
    """Location 스키마 생성 중복 제거.

    Args:
        is_campus (bool): 캠퍼스 여부.
        building (str | None): 건물 이름.
        naver_link (str | None): 네이버 지도 링크.
        kakao_link (str | None): 카카오 지도 링크.
        lat (float | None): 위도.
        lon (float | None): 경도.

    Returns:
        Location: Location 스키마.
    """
    return Location(
        is_campus=is_campus,
        building=building,
        map_links=build_map_links(naver_link, kakao_link),
        latitude=lat,
        longitude=lon,
    )


def build_restaurant_schema(
    restaurant: Restaurant,
    operating_hours: dict[str, TimeRange],
) -> RestaurantResponse:
    """RestaurantResponse 스키마 생성.

    Args:
        restaurant (Restaurant): 식당 객체.
        operating_hours (dict[str, TimeRange]): 운영 시간 정보.

    Returns:
        RestaurantResponse: RestaurantResponse 스키마.
    """
    return RestaurantResponse(
        id=restaurant.id,
        name=restaurant.name,
        owner=restaurant.owner,
        establishment_type=restaurant.establishment_type,  # type: ignore
        location=Location(
            is_campus=restaurant.is_campus,
            building=restaurant.building_name,
            map_links=build_map_links(
                restaurant.naver_map_link, restaurant.kakao_map_link
            ),
            latitude=restaurant.latitude,
            longitude=restaurant.longitude,
        ),
        opening_time=operating_hours.get("opening_time"),
        break_time=operating_hours.get("break_time"),
        breakfast_time=operating_hours.get("breakfast_time"),
        brunch_time=operating_hours.get("brunch_time"),
        lunch_time=operating_hours.get("lunch_time"),
        dinner_time=operating_hours.get("dinner_time"),
    )


async def get_submission_or_404(
    db: AsyncSession, request_id: int
) -> RestaurantSubmission:
    """Submission을 조회하고, 없으면 404 예외를 발생시킨다.

    Args:
        db (AsyncSession): 데이터베이스 세션.
        request_id (int): 요청 ID.

    Returns:
        RestaurantSubmission: 조회된 제출 객체.

    Raises:
        HTTPException: 제출 객체가 존재하지 않을 때 발생.
    """
    result = await db.execute(
        select(RestaurantSubmission).filter(RestaurantSubmission.id == request_id)
    )
    submission = result.scalars().first()
    if not submission:
        raise HTTPException(
            status_code=404, detail="해당 제출 요청이 존재하지 않습니다."
        )
    return submission


async def get_restaurant_or_404(db: AsyncSession, restaurant_id: int) -> Restaurant:
    """Restaurant를 조회하고, 없으면 404 예외를 발생시킨다.

    Args:
        db (AsyncSession): 데이터베이스 세션.
        restaurant_id (int): 식당 ID.

    Returns:
        Restaurant: 조회된 식당 객체.

    Raises:
        HTTPException: 식당 객체가 존재하지 않을 때 발생.
    """
    result = await db.execute(select(Restaurant).filter(Restaurant.id == restaurant_id))
    restaurant = result.scalars().first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="해당 식당이 존재하지 않습니다.")
    return restaurant


def validate_time_range(key: str, value: TimeRange):
    """TimeRange 유효성 검증.

    Args:
        key (str): 시간 범위 키.
        value (TimeRange): 시간 범위 값.

    Returns:
        OperatingHours: 유효성 검증된 운영 시간 객체.

    Raises:
        HTTPException: 시간 범위가 유효하지 않을 때 발생.
    """
    value.to_datetime()

    if not (isinstance(value.start, datetime) and isinstance(value.end, datetime)):
        raise HTTPException(status_code=400, detail=f"{key}의 시간이 올바르지 않습니다.")
    if value.start >= value.end:
        raise HTTPException(
            status_code=400, detail=f"{key}의 시작 시간이 종료 시간보다 늦습니다."
        )
    if not (
        get_datetime_by_string("00:00")
        <= value.start
        <= get_datetime_by_string("23:59")
    ) or not (
        get_datetime_by_string("00:00") <= value.end <= get_datetime_by_string("23:59")
    ):
        raise HTTPException(
            status_code=400, detail=f"{key}의 시간이 올바르지 않습니다."
        )

    value.to_string()
    return OperatingHours(type=key, start_time=value.start, end_time=value.end)


def build_operating_hours_entries(
    operation_hours_dict, submission_id=None, restaurant_id=None
):
    """운영시간 리스트를 생성.

    Args:
        operation_hours_dict (dict): 운영 시간 정보 딕셔너리.
        submission_id (int | None, optional): 제출 ID.
        restaurant_id (int | None, optional): 식당 ID.

    Returns:
        list: 운영 시간 객체 리스트.
    """
    operating_hours_entries = []

    for key, value in operation_hours_dict.items():
        if value:
            entry = validate_time_range(key, value)
            entry.submission_id = submission_id
            entry.restaurant_id = restaurant_id
            operating_hours_entries.append(entry)

    return operating_hours_entries
