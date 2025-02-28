import time
from fastapi_pagination import Params
from fastapi_pagination.bases import AbstractPage
from pydantic import BaseModel
from typing import Generic, List, Optional, TypeVar

T = TypeVar("T")


class MetaData(BaseModel):
    page: int
    size: int
    total: int
    has_next: bool
    has_prev: bool


class CustomPage(AbstractPage[T], Generic[T]):
    status: str = "success"
    meta: MetaData
    data: List[T]  # items → data로 변경

    # ✅ __params_type__을 명확하게 지정해야 AttributeError 방지됨
    __params_type__ = Params

    @classmethod
    def create(cls, data: List[T], total: int, params: Params) -> "CustomPage[T]":
        total_pages = (total + params.size - 1) // params.size

        return cls(
            meta=MetaData(
                page=params.page,
                size=params.size,
                total=total,
                has_next=params.page < total_pages,
                has_prev=params.page > 1,
            ),
            data=data,  # 변경된 필드 적용
        )
