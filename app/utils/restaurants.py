from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.restaurants import OperatingHours, Restaurant
from app.schemas.restaurants import Location, RestaurantResponse
from app.schemas.restaurants import TimeRange


async def fetch_operating_hours_dict(
    db: AsyncSession,
    *,
    submission_id: int | None = None,
    restaurant_id: int | None = None,
) -> dict[str, TimeRange]:
    """submission_id나 restaurant_id를 받아 OperatingHours를 조회한 뒤, dict로 변환"""
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
    map_links = {}
    if naver_link:
        map_links["naver"] = naver_link
    if kakao_link:
        map_links["kakao"] = kakao_link
    return map_links if map_links else None


def build_location_schema(
    is_campus: bool,
    building: str | None,
    naver_link: str | None,
    kakao_link: str | None,
    lat: float | None,
    lon: float | None,
) -> Location:
    """Location 스키마 생성 중복 제거"""
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
