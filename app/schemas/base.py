from typing import Generic, TypeVar
from datetime import datetime

from pydantic import BaseModel, GetCoreSchemaHandler
from pydantic_core import core_schema

from app.config import Config


T = TypeVar("T")


class MetaData(BaseModel):
    total: int = 1


class BaseSchema(BaseModel, Generic[T]):
    status: str = "success"
    meta: MetaData = MetaData()
    data: T


class Timestamp:
    """KST(서울 시간)으로 자동 변환되는 datetime 필드"""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler: GetCoreSchemaHandler):
        """Pydantic이 사용할 스키마를 정의"""
        return core_schema.no_info_after_validator_function(
            cls.convert_to_kst, handler.generate_schema(datetime)
        )

    @classmethod
    def convert_to_kst(cls, value: str | datetime) -> datetime:
        """ISO 8601 문자열 또는 datetime을 받아 KST 변환"""
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is None:
                    # ✅ 타임존이 없는 경우, 기본적으로 KST로 간주
                    dt = dt.replace(tzinfo=Config.TZ)
                else:
                    # ✅ 타임존이 있는 경우, KST로 변환
                    dt = dt.astimezone(Config.TZ)
                return dt
            except ValueError as err:
                raise ValueError(f"Invalid ISO 8601 format: {value}") from err

        elif isinstance(value, datetime):
            if value.tzinfo is None:
                # ✅ datetime 객체에 타임존이 없으면 KST로 간주
                return value.replace(tzinfo=Config.TZ)
            else:
                return value.astimezone(Config.TZ)
        else:
            raise TypeError(f"Expected str or datetime, got {type(value)}")
