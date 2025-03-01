from datetime import datetime
from enum import Enum
from typing import Dict, Literal, Optional

from pydantic import BaseModel

from app.utils.times import get_datetime_by_string


class TimeRange(BaseModel):
    start: str | datetime  # "HH:MM" 형식
    end: str | datetime  # "HH:MM" 형식

    def to_datetime(self):
        if isinstance(self.start, str):
            self.start = get_datetime_by_string(self.start)
        if isinstance(self.end, str):
            self.end = get_datetime_by_string(self.end)

    def to_string(self):
        if isinstance(self.start, datetime):
            self.start = self.start.strftime("%H:%M")
        if isinstance(self.end, datetime):
            self.end = self.end.strftime("%H:%M")


class LocationType(str, Enum):
    CAMPUS = "campus"
    OFF_CAMPUS = "off_campus"


class Location(BaseModel):
    type: LocationType  # "campus" 또는 "off_campus"
    building: Optional[str] = None
    map_links: Optional[Dict[str, str]] = None  # 네이버, 카카오 지도 링크
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class Restaurant(BaseModel):
    name: str
    type: Literal["student", "vendor", "external"]
    location: Optional[Location] = None
    opening_time: Optional[TimeRange] = None
    break_time: Optional[TimeRange] = None
    breakfast_time: Optional[TimeRange] = None
    brunch_time: Optional[TimeRange] = None
    lunch_time: Optional[TimeRange] = None
    dinner_time: Optional[TimeRange] = None


class RestaurantResponse(Restaurant):
    """GET /restaurants/{id} 엔드포인트 응답 바디"""

    id: int


class RestaurantRequest(Restaurant):
    """POST /restaurants/requests 엔드포인트 요청 바디"""


class SubmissionResponse(BaseModel):
    status: str = "pending"
    request_id: int
    message: Optional[str] = "등록 요청이 성공적으로 접수되었습니다."

class UserSchema(BaseModel):
    id: int
    name: str
    email: str
    is_admin: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    class Config:
        extra = "allow"  # 정의되지 않은 필드도 허용