from typing import List

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer

from app.database import Base
from app.models.associations import restaurant_manager_association


class User(Base):
    """사용자 정보를 저장하는 클래스 (User API 연동)"""

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
