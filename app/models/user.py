# ruff: noqa: F821
"""이 모듈은 사용자 정보를 저장하는 User 클래스를 정의합니다."""

from typing import List

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer

from app.database import Base
from app.models.associations import restaurant_manager_association


class User(Base):
    """사용자 정보를 저장하는 클래스 (User API 연동)

    속성:
        id (int): 사용자의 고유 ID
        owned_restaurants (List[Restaurant]): 사용자가 소유한 레스토랑 목록
        managed_restaurants (List[Restaurant]): 사용자가 관리하는 레스토랑 목록
        submitted_restaurants (List[RestaurantSubmission]): 사용자가 제출한 레스토랑 제출 목록
    """

    __tablename__ = "User"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owned_restaurants: Mapped[List["Restaurant"]] = relationship(
        "Restaurant", back_populates="owner_user"
    )
    managed_restaurants: Mapped[List["Restaurant"]] = relationship(
        "Restaurant",
        secondary=restaurant_manager_association,
        back_populates="managers",
    )
    submitted_restaurants: Mapped[List["RestaurantSubmission"]] = relationship(
        "RestaurantSubmission", back_populates="submitter_user"
    )
