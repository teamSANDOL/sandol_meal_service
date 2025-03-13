"""이 모듈은 레스토랑 관련 데이터 스키마를 정의합니다.

Pydantic BaseModel을 사용하여 데이터 유효성 검사를 수행합니다.
"""

from datetime import datetime
from typing import Dict, Literal, Optional

from pydantic import BaseModel

from app.utils.times import get_datetime_by_string


class TimeRange(BaseModel):
    """시간 범위를 나타내는 클래스입니다.

    Attributes:
        start (str | datetime): 시작 시간 ("HH:MM" 형식 또는 datetime 객체)
        end (str | datetime): 종료 시간 ("HH:MM" 형식 또는 datetime 객체)
    """

    start: str | datetime  # "HH:MM" 형식
    end: str | datetime  # "HH:MM" 형식

    def to_datetime(self):
        """start와 end 속성을 문자열에서 datetime 객체로 변환합니다."""
        if isinstance(self.start, str):
            self.start = get_datetime_by_string(self.start)
        if isinstance(self.end, str):
            self.end = get_datetime_by_string(self.end)

    def to_string(self):
        """start와 end 속성을 datetime 객체에서 문자열로 변환합니다."""
        if isinstance(self.start, datetime):
            self.start = self.start.strftime("%H:%M")
        if isinstance(self.end, datetime):
            self.end = self.end.strftime("%H:%M")


class Location(BaseModel):
    """레스토랑의 위치를 나타내는 클래스입니다.

    Attributes:
        is_campus (bool): 캠퍼스 내 위치 여부
        building (Optional[str]): 건물 이름
        map_links (Optional[Dict[str, str]]): 네이버, 카카오 지도 링크
        latitude (Optional[float]): 위도
        longitude (Optional[float]): 경도
    """

    is_campus: bool
    building: Optional[str] = None
    map_links: Optional[Dict[str, str]] = None  # 네이버, 카카오 지도 링크
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class RestaurantSchema(BaseModel):
    """레스토랑의 기본 정보를 나타내는 클래스입니다.

    Attributes:
        name (str): 레스토랑 이름
        establishment_type (Literal["student", "vendor", "external"]): 레스토랑 유형
        location (Optional[Location]): 위치 정보
        opening_time (Optional[TimeRange]): 영업 시간
        break_time (Optional[TimeRange]): 휴식 시간
        breakfast_time (Optional[TimeRange]): 아침 식사 시간
        brunch_time (Optional[TimeRange]): 브런치 시간
        lunch_time (Optional[TimeRange]): 점심 시간
        dinner_time (Optional[TimeRange]): 저녁 시간
    """

    name: str
    establishment_type: Literal["student", "vendor", "external"]
    location: Optional[Location] = None
    opening_time: Optional[TimeRange] = None
    break_time: Optional[TimeRange] = None
    breakfast_time: Optional[TimeRange] = None
    brunch_time: Optional[TimeRange] = None
    lunch_time: Optional[TimeRange] = None
    dinner_time: Optional[TimeRange] = None


class RestaurantResponse(RestaurantSchema):
    """GET /restaurants/{id} 및 /restaurants 엔드포인트 응답 바디를 나타내는 클래스입니다.

    Attributes:
        id (int): 레스토랑 ID
        owner (Optional[int]): 소유자 ID
    """

    id: int
    owner: Optional[int] = None


class RestaurantRequest(RestaurantSchema):
    """POST /restaurants/requests 엔드포인트 요청 바디를 나타내는 클래스입니다."""


class RestaurantSubmission(RestaurantSchema):
    """레스토랑 제출 정보를 나타내는 클래스입니다.

    Attributes:
        status (Literal["pending", "approved", "rejected"]): 제출 상태
        submitter (int): 제출자 ID
        submitted_time (datetime): 제출 시간
        id (int): 제출 ID
        reviewed_time (Optional[datetime]): 검토 시간
        reviewer (Optional[int]): 검토자 ID
        rejection_message (Optional[str]): 거절 메시지
    """

    status: Literal["pending", "approved", "rejected"] = "pending"
    submitter: int
    submitted_time: datetime
    id: int
    reviewed_time: Optional[datetime] = None
    reviewer: Optional[int] = None
    rejection_message: Optional[str] = None


class SubmissionResponse(BaseModel):
    """제출 응답을 나타내는 클래스입니다.

    Attributes:
        status (str): 제출 상태
        request_id (int): 요청 ID
        message (Optional[str]): 응답 메시지
    """

    status: str = "pending"
    request_id: int
    message: Optional[str] = "등록 요청이 성공적으로 접수되었습니다."


class ApproverResponse(BaseModel):
    """승인 응답을 나타내는 클래스입니다.

    Attributes:
        status (str): 승인 상태
        restaurant_id (int): 레스토랑 ID
        message (Optional[str]): 응답 메시지
    """

    status: str = "approved"
    restaurant_id: int
    message: Optional[str] = "등록 요청이 승인되었습니다."


class UserSchema(BaseModel):
    """사용자 정보를 나타내는 클래스입니다.

    Attributes:
        id (int): 사용자 ID
        name (str): 사용자 이름
        email (str): 사용자 이메일
        is_admin (bool): 관리자 여부
        is_active (bool): 활성화 여부
        created_at (datetime): 생성 시간
        updated_at (datetime): 업데이트 시간
        last_login (Optional[datetime]): 마지막 로그인 시간
    """

    id: int
    name: str
    email: str
    is_admin: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        """정의되지 않은 필드도 허용합니다."""
        extra = "allow"


class RejectRestaurantRequest(BaseModel):
    """레스토랑 요청 거절 메시지를 나타내는 클래스입니다.

    Attributes:
        message (str): 거절 메시지
    """

    message: str
