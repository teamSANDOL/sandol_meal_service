from sqlalchemy import Column, BigInteger, Table, ForeignKey

from app.database import Base

# Restaurant와 User 사이의 Many-to-Many 관계를 정의하는 테이블
restaurant_manager_association = Table(
    "RestaurantManager",
    Base.metadata,
    Column("restaurant_id", BigInteger, ForeignKey(
        "Restaurant.id"), primary_key=True),
    Column("user_id", BigInteger, ForeignKey("User.id"), primary_key=True),
)
