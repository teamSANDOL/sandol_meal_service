"""이 모듈은 페이지네이션을 위한 스키마를 정의합니다.

Pydantic과 FastAPI Pagination을 사용하여 페이지네이션 메타데이터와 페이지 데이터를 포함하는 커스텀 페이지 클래스를 제공합니다.
"""

from typing import Generic, List, TypeVar

from fastapi_pagination import Params
from fastapi_pagination.bases import AbstractPage
from pydantic import BaseModel

T = TypeVar("T")


class MetaData(BaseModel):
    """페이지네이션 메타데이터를 나타내는 클래스.

    Attributes:
        page (int): 현재 페이지 번호.
        size (int): 페이지당 항목 수.
        total (int): 전체 항목 수.
        has_next (bool): 다음 페이지 존재 여부.
        has_prev (bool): 이전 페이지 존재 여부.
    """

    page: int
    size: int
    total: int
    has_next: bool
    has_prev: bool


class CustomPage(AbstractPage[T], Generic[T]):
    """페이지네이션 데이터를 포함하는 커스텀 페이지 클래스.

    Attributes:
        status (str): 상태를 나타내는 문자열. 기본값은 "success".
        meta (MetaData): 페이지네이션 메타데이터 객체.
        data (List[T]): 페이지 데이터 리스트.
    """

    status: str = "success"
    meta: MetaData
    data: List[T]  # items → data로 변경

    # ✅ __params_type__을 명확하게 지정해야 AttributeError 방지됨
    __params_type__ = Params

    @classmethod
    def create(cls, data: List[T], total: int, params: Params) -> "CustomPage[T]":
        """주어진 데이터와 페이지네이션 파라미터를 사용하여 CustomPage 객체를 생성합니다.

        Args:
            data (List[T]): 페이지 데이터 리스트.
            total (int): 전체 항목 수.
            params (Params): 페이지네이션 파라미터 객체.

        Returns:
            CustomPage[T]: 생성된 CustomPage 객체.
        """
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
