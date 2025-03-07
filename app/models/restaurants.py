from __future__ import annotations
from typing import List, Optional
from datetime import datetime

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
from sqlalchemy.sql import func

from app.database import Base
from app.models.associations import restaurant_manager_association


class Restaurant(Base):
    """식당 정보를 저장하는 클래스"""

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
    """식당 정보 제출을 관리하는 클래스"""

    __tablename__ = "Restaurant_submission"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    submitter: Mapped[int] = mapped_column(
        Integer, ForeignKey("User.id"), nullable=False
    )
    submitted_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    approver: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approved_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )
    establishment_type: Mapped[str] = mapped_column(Text, nullable=False)

    is_campus: Mapped[bool] = mapped_column(Boolean, nullable=False)
    building_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    naver_map_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kakao_map_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float(53), nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float(53), nullable=True)

    submitter_user: Mapped["User"] = relationship("User", foreign_keys=[submitter])

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
    """식당의 운영시간을 저장하는 클래스"""

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
