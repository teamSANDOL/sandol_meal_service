import time
from fastapi_pagination import Params
from fastapi_pagination.bases import AbstractPage
from pydantic import BaseModel
from typing import Generic, List, TypeVar

T = TypeVar("T")

class MetaData(BaseModel):
    page: int
    size: int
    total: int
    has_next: bool
    has_prev: bool
    response_time: float  # 응답 시간(ms)

class CustomPage(AbstractPage[T], Generic[T]):
    status: str = "success"
    meta: MetaData
    data: List[T]  # items → data로 변경

    @classmethod
    def create(cls, data: List[T], total: int, params: Params, start_time: float) -> "CustomPage[T]":
        total_pages = (total + params.size - 1) // params.size
        response_time = round((time.time() - start_time) * 1000, 2)  # ms 단위 응답 시간 계산

        return cls(
            meta=MetaData(
                page=params.page,
                size=params.size,
                total=total,
                has_next=params.page < total_pages,
                has_prev=params.page > 1,
                response_time=response_time
            ),
            data=data,  # 변경된 필드 적용
        )
