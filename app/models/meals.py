from __future__ import annotations
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

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
from sqlalchemy.types import TypeDecorator, JSON

from app.database import Base
from app.models.restaurants import Restaurant

class NonEscapedJSON(TypeDecorator):
    """한글이 유니코드로 저장되지 않도록 하는 JSON 타입"""
    
    impl = JSON

    def process_bind_param(self, value, dialect):
        """DB에 저장하기 전 변환 (한글이 유니코드 이스케이프 되지 않도록 설정)"""
        if value is not None:
            return json.dumps(value, ensure_ascii=False)
        return value

    def process_result_value(self, value, dialect):
        """DB에서 가져올 때 변환"""
        if value is not None:
            return json.loads(value)
        return value

class MealType(Base):
    """식사 유형을 저장하는 클래스 (예: breakfast, brunch, lunch, dinner)"""

    __tablename__ = "meal_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 예: "breakfast", "brunch", "lunch", "dinner"
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


class Meal(Base):
    """식단 정보를 저장하는 클래스"""

    __tablename__ = "meal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    restaurant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("Restaurant.id"), nullable=False)
    menu: Mapped[List[str]] = mapped_column(NonEscapedJSON, nullable=False, default={})
    registered_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now())

    meal_type_id: Mapped[int] = mapped_column(Integer, ForeignKey("meal_type.id"), nullable=False)

    # 관계 설정
    restaurant: Mapped[Restaurant] = relationship("Restaurant", back_populates="meals")
    meal_type: Mapped[MealType] = relationship("MealType")

    __table_args__ = (
        Index("meal_restaurant_id_index", "restaurant_id"),
    )
