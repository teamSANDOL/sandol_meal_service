from __future__ import annotations
from typing import List, Optional, Dict, Any
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    TIMESTAMP,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base
from app.models.restaurants import Restaurant


class MealType(Base):
    """식사 유형을 저장하는 클래스 (예: breakfast, brunch, lunch, dinner)"""

    __tablename__ = "meal_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 예: "breakfast", "brunch", "lunch", "dinner"
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


class Meal(Base):
    """식단 정보를 저장하는 클래스"""

    __tablename__ = "Meal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    restaurant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("Restaurant.id"), nullable=False)
    menu: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default={})
    registered_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())

    meal_type_id: Mapped[int] = mapped_column(Integer, ForeignKey("meal_type.id"), nullable=False)

    # 관계 설정
    restaurant: Mapped[Restaurant] = relationship("Restaurant", back_populates="meals")
    meal_type: Mapped[MealType] = relationship("MealType")

    __table_args__ = (
        Index("meal_restaurant_id_index", "restaurant_id"),
    )
