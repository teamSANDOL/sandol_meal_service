from sqlalchemy import Column, Integer, BigInteger, Text, TIMESTAMP, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from sqlalchemy.sql import func

from app.database import Base


class MealType(Base):
    """식사 유형을 저장하는 클래스 (예: breakfast, brunch, lunch, dinner)"""

    __tablename__ = "meal_type"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 예: "breakfast", "brunch", "lunch", "dinner"
    name = Column(Text, nullable=False, unique=True)


class Meal(Base):
    """식단 정보를 저장하는 클래스"""

    __tablename__ = "Meal"

    id = Column(Integer, primary_key=True, autoincrement=True)
    restaurant_id = Column(BigInteger, ForeignKey(
        "Restaurant.id"), nullable=False)
    menu = Column(JSON, nullable=False, default={})
    registered_at = Column(TIMESTAMP, nullable=False,
                           server_default=func.now())

    meal_type_id = Column(Integer, ForeignKey("meal_type.id"), nullable=False)

    # 관계 설정
    restaurant = relationship("Restaurant", back_populates="meals")
    meal_type = relationship("MealType")

    __table_args__ = (
        Index("meal_restaurant_id_index", "restaurant_id"),
    )
