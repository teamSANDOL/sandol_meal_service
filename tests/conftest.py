"""Shared fixtures for meal-service tests."""

import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import Base, async_engine
from app.models.meals import MealType
from app.models.restaurants import Restaurant
from app.models.user import User


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """Create an isolated in-memory database with minimal seed data."""
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        async_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        user = User(user_id="test-user")
        session.add(user)
        await session.flush()
        session.add_all(
            [
                Restaurant(
                    name="TIP",
                    owner=user.id,
                    is_campus=True,
                    establishment_type="student",
                ),
                Restaurant(
                    name="E동",
                    owner=user.id,
                    is_campus=True,
                    establishment_type="student",
                ),
                MealType(name="breakfast"),
                MealType(name="brunch"),
                MealType(name="lunch"),
                MealType(name="dinner"),
            ]
        )
        await session.commit()
        yield session
    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await async_engine.dispose()
