"""이 모듈은 식당(Restaurant) 및 관련 데이터베이스 모델을 정의합니다.

식당 정보, 식당 제출 정보, 운영 시간 등의 클래스를 포함합니다.
"""

from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    DateTime,
    Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.inspection import inspect

from app.config.config import Config
from app.database import Base
from app.models.associations import restaurant_manager_association

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.meals import Meal


class Restaurant(Base):
    """식당 정보를 저장하는 클래스

    Attributes:
        id (int): 식당의 고유 식별자
        name (str): 식당 이름
        owner (int): 식당 소유자의 사용자 ID
        is_campus (bool): 캠퍼스 내 식당 여부
        establishment_type (str): 식당 유형
        building_name (Optional[str]): 건물 이름
        naver_map_link (Optional[str]): 네이버 지도 링크
        kakao_map_link (Optional[str]): 카카오 지도 링크
        latitude (Optional[float]): 위도
        longitude (Optional[float]): 경도
        owner_user (User): 소유자 사용자 객체
        managers (List[User]): 식당 관리자 사용자 객체 목록
        operating_hours (List[OperatingHours]): 운영 시간 객체 목록
        meals (List[Meal]): 식사 객체 목록
    """

    __tablename__ = "Restaurant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[int] = mapped_column(Integer, ForeignKey("User.id"), nullable=False)
    is_campus: Mapped[bool] = mapped_column(Boolean, nullable=False)
    establishment_type: Mapped[str] = mapped_column(Text, nullable=False)

    building_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    naver_map_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kakao_map_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float(53), nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float(53), nullable=True)

    owner_user: Mapped["User"] = relationship("User", foreign_keys=[owner])

    # ✅ managers 관계 추가 (다대다 관계 설정)
    managers: Mapped[List["User"]] = relationship(
        "User",
        secondary=restaurant_manager_association,
        back_populates="managed_restaurants",
        passive_deletes=True,
    )

    # ✅ 1:N 관계 유지
    operating_hours: Mapped[List["OperatingHours"]] = relationship(
        "OperatingHours",
        back_populates="restaurant",
        foreign_keys="[OperatingHours.restaurant_id]",
        cascade="all, delete-orphan",
    )

    meals: Mapped[List["Meal"]] = relationship("Meal", back_populates="restaurant")

    __table_args__ = (
        Index("restaurant_name_index", "name"),
        Index("restaurant_owner_index", "owner"),
    )


class RestaurantSubmission(Base):
    """식당 정보 제출을 관리하는 클래스

    Attributes:
        id (int): 제출의 고유 식별자
        name (str): 제출된 식당 이름
        status (str): 제출 상태("pending", "approved", "rejected")
        submitter (int): 제출자 사용자 ID
        submitted_time (datetime): 제출 시간
        reviewer (Optional[int]): 검토자 사용자 ID
        reviewed_time (Optional[datetime]): 검토 시간
        rejection_message (Optional[str]): 거절 메시지
        establishment_type (str): 식당 유형
        is_campus (bool): 캠퍼스 내 식당 여부
        building_name (Optional[str]): 건물 이름
        naver_map_link (Optional[str]): 네이버 지도 링크
        kakao_map_link (Optional[str]): 카카오 지도 링크
        latitude (Optional[float]): 위도
        longitude (Optional[float]): 경도
        submitter_user (User): 제출자 사용자 객체
        operating_hours (List[OperatingHours]): 운영 시간 객체 목록
    """

    __tablename__ = "Restaurant_submission"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    submitter: Mapped[int] = mapped_column(
        Integer, ForeignKey("User.id"), ondelete="CASCADE",
        nullable=False,
    )
    submitted_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    reviewer: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reviewed_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=lambda: datetime.now(timezone.utc),
    )
    rejection_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    establishment_type: Mapped[str] = mapped_column(Text, nullable=False)

    is_campus: Mapped[bool] = mapped_column(Boolean, nullable=False)
    building_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    naver_map_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kakao_map_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float(53), nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float(53), nullable=True)

    submitter_user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[submitter],
        passive_deletes=True,
    )

    # ✅ 여러 개의 OperatingHours가 연결될 수 있도록 수정
    operating_hours: Mapped[List["OperatingHours"]] = relationship(
        "OperatingHours",
        back_populates="restaurant_submission",
        foreign_keys="[OperatingHours.submission_id]",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("restaurant_submission_name_index", "name"),
        Index("restaurant_submission_status_index", "status"),
        Index("restaurant_submission_submitter_index", "submitter"),
    )


class OperatingHours(Base):
    """식당의 운영시간을 저장하는 클래스

    Attributes:
        id (int): 운영 시간의 고유 식별자
        type (str): 운영 시간 유형
        start_time (str): 시작 시간
        end_time (str): 종료 시간
        restaurant_id (Optional[int]): 연결된 식당의 ID
        submission_id (Optional[int]): 연결된 제출의 ID
        restaurant (Restaurant): 연결된 식당 객체
        restaurant_submission (RestaurantSubmission): 연결된 식당 등록 신청 객체
    """

    __tablename__ = "operating_hours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[str] = mapped_column(Text, nullable=False)
    end_time: Mapped[str] = mapped_column(Text, nullable=False)

    # ✅ Restaurant와 1:N 관계
    restaurant_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("Restaurant.id"), nullable=True
    )

    # ✅ RestaurantSubmission과 1:N 관계
    submission_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("Restaurant_submission.id"), nullable=True
    )

    # ✅ 1:N 관계 명확하게 지정
    restaurant: Mapped["Restaurant"] = relationship(
        "Restaurant", back_populates="operating_hours", foreign_keys=[restaurant_id]
    )

    restaurant_submission: Mapped["RestaurantSubmission"] = relationship(
        "RestaurantSubmission",
        back_populates="operating_hours",
        foreign_keys=[submission_id],
    )

    # ✅ CHECK 제약 조건 추가 (restaurant_id 또는 submission_id 중 하나만 존재해야 함)
    __table_args__ = (
        CheckConstraint(
            "(restaurant_id IS NOT NULL AND submission_id IS NULL) OR "
            "(restaurant_id IS NULL AND submission_id IS NOT NULL)",
            name="check_one_foreign_key_not_null",
        ),
    )
