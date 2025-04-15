from datetime import datetime
from pydantic import BaseModel


class UserCreate(BaseModel):
    id: int
    meal_admin: bool = False


class UserRead(BaseModel):
    id: int
    mead_admin: bool = False

    class Config:
        from_attributes = True


class UserSchema(BaseModel):
    """사용자 정보를 나타내는 클래스입니다.

    Attributes:
        id (int): 사용자 ID
        name (str): 사용자 이름
        email (str): 사용자 이메일
        global_admin (bool) = 전역 관리자 여부
        service_account (bool) = 서비스 API 계정 여부
        created_at (datetime): 생성 시간
    """

    id: int
    name: str
    email: str
    global_admin: bool = False
    service_account: bool = False
    created_at: datetime

    class Config:
        """정의되지 않은 필드도 허용합니다."""

        extra = "allow"
