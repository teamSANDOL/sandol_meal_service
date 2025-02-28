from sqlalchemy import (
    Column,
    BigInteger,
    Text,
    Float,
    TIMESTAMP,
    ForeignKey,
    Index,
    CheckConstraint,
)
from sqlalchemy.orm import relationship
from app.models.associations import restaurant_manager_association
from app.database import Base


class Restaurant(Base):
    """식당 정보를 저장하는 클래스"""

    __tablename__ = "Restaurant"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    owner = Column(BigInteger, ForeignKey("User.id"), nullable=False)
    location_type = Column(Text, nullable=False)

    building_name = Column(Text, nullable=True)
    naver_map_link = Column(Text, nullable=True)
    kakao_map_link = Column(Text, nullable=True)
    latitude = Column(Float(53), nullable=True)
    longitude = Column(Float(53), nullable=True)

    owner_user = relationship("User", foreign_keys=[owner])

    # ✅ managers 관계 추가 (다대다 관계 설정)
    managers = relationship(
        "User",
        secondary=restaurant_manager_association,
        back_populates="managed_restaurants"
    )

    # ✅ 1:N 관계 유지
    operating_hours = relationship(
        "OperatingHours",
        back_populates="restaurant",
        foreign_keys="[OperatingHours.restaurant_id]",
        cascade="all, delete-orphan"
    )

    meals = relationship("Meal", back_populates="restaurant")

    __table_args__ = (
        Index("restaurant_name_index", "name"),
        Index("restaurant_owner_index", "owner"),
    )


class RestaurantSubmission(Base):
    """식당 정보 제출을 관리하는 클래스"""

    __tablename__ = "Restaurant_submission"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    submitter = Column(BigInteger, ForeignKey("User.id"), nullable=False)
    submitted_time = Column(TIMESTAMP, nullable=False)
    approver = Column(BigInteger, nullable=True)
    approved_time = Column(TIMESTAMP, nullable=True)
    location_type = Column(Text, nullable=False)

    building_name = Column(Text, nullable=True)
    naver_map_link = Column(Text, nullable=True)
    kakao_map_link = Column(Text, nullable=True)
    latitude = Column(Float(53), nullable=True)
    longitude = Column(Float(53), nullable=True)

    submitter_user = relationship("User", foreign_keys=[submitter])

    # ✅ 여러 개의 OperatingHours가 연결될 수 있도록 수정
    operating_hours = relationship(
        "OperatingHours",
        back_populates="restaurant_submission",
        foreign_keys="[OperatingHours.submission_id]",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("restaurant_submission_name_index", "name"),
        Index("restaurant_submission_status_index", "status"),
        Index("restaurant_submission_submitter_index", "submitter"),
    )


class OperatingHours(Base):
    """식당의 운영시간을 저장하는 클래스"""

    __tablename__ = "operating_hours"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    type = Column(Text, nullable=False)
    start_time = Column(Text, nullable=False)
    end_time = Column(Text, nullable=False)

    # ✅ Restaurant와 1:N 관계
    restaurant_id = Column(BigInteger, ForeignKey(
        "Restaurant.id"), nullable=True)

    # ✅ RestaurantSubmission과 1:N 관계
    submission_id = Column(BigInteger, ForeignKey(
        "Restaurant_submission.id"), nullable=True)

    # ✅ 1:N 관계 명확하게 지정
    restaurant = relationship(
        "Restaurant",
        back_populates="operating_hours",
        foreign_keys=[restaurant_id]
    )

    restaurant_submission = relationship(
        "RestaurantSubmission",
        back_populates="operating_hours",
        foreign_keys=[submission_id]
    )

    # ✅ CHECK 제약 조건 추가 (restaurant_id 또는 submission_id 중 하나만 존재해야 함)
    __table_args__ = (
        CheckConstraint(
            "(restaurant_id IS NOT NULL AND submission_id IS NULL) OR "
            "(restaurant_id IS NULL AND submission_id IS NOT NULL)",
            name="check_one_foreign_key_not_null",
        ),
    )


class User(Base):
    """사용자 정보를 저장하는 클래스 (User API 연동)"""

    __tablename__ = "User"

    id = Column(BigInteger, primary_key=True)

    owned_restaurants = relationship("Restaurant", back_populates="owner_user")
    managed_restaurants = relationship(
        "Restaurant",
        secondary=restaurant_manager_association,
        back_populates="managers",
    )
    submitted_restaurants = relationship(
        "RestaurantSubmission", back_populates="submitter_user"
    )
