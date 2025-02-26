from sqlalchemy import Column, BigInteger, Text, Float, TIMESTAMP, ForeignKey, Index, CheckConstraint
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
    operating_hours_id = Column(BigInteger, ForeignKey("operating_hours.id"), nullable=True)
    building_name = Column(Text, nullable=True)
    naver_map_link = Column(Text, nullable=True)
    kakao_map_link = Column(Text, nullable=True)
    latitude = Column(Float(53), nullable=True)
    longitude = Column(Float(53), nullable=True)

    # 관계 설정
    owner_user = relationship("User", foreign_keys=[owner])
    managers = relationship(
        "User",
        secondary=restaurant_manager_association,
        back_populates="managed_restaurants",
    )
    operating_hours_obj = relationship("OperatingHours", back_populates="restaurant")
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
    operating_hours_id = Column(BigInteger, ForeignKey("operating_hours.id"), nullable=True)
    building_name = Column(Text, nullable=True)
    naver_map_link = Column(Text, nullable=True)
    kakao_map_link = Column(Text, nullable=True)
    latitude = Column(Float(53), nullable=True)
    longitude = Column(Float(53), nullable=True)

    submitter_user = relationship("User", foreign_keys=[submitter])
    operating_hours_obj = relationship(
        "OperatingHours", back_populates="restaurant_submission"
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

    restaurant_id = Column(BigInteger, ForeignKey("Restaurant.id"), nullable=True)
    submission_id = Column(BigInteger, ForeignKey("Restaurant_submission.id"), nullable=True)

    # CHECK 제약 조건 추가 (restaurant_id 또는 submission_id 중 하나만 존재해야 함)
    __table_args__ = (
        CheckConstraint(
            "(restaurant_id IS NOT NULL AND submission_id IS NULL) OR "
            "(restaurant_id IS NULL AND submission_id IS NOT NULL)",
            name="check_one_foreign_key_not_null"
        ),
    )

    # 관계 설정
    restaurant = relationship("Restaurant", back_populates="operating_hours_obj")
    restaurant_submission = relationship(
        "RestaurantSubmission", back_populates="operating_hours_obj"
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
