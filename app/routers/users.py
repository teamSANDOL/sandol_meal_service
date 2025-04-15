"""카카오 챗봇 서비스의 사용자 관련 API를 정의합니다.

이 모듈은 사용자 생성, 조회, 목록 조회 및 삭제 기능을 제공합니다.
사용자 정보는 외부 사용자 서비스에서 가져오며, SQLAlchemy를 사용하여 데이터베이스와 상호작용합니다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.config import Config
from app.models.user import User
from app.schemas.users import UserCreate, UserRead
from app.utils.db import get_db, get_user_info, get_async_client

user_router = APIRouter(prefix="/users", tags=["User"])


@user_router.post("/", response_model=UserRead)
async def create_user(
    user_in: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    client: Annotated[AsyncClient, Depends(get_async_client)],
):
    """Create a new user.

    외부 사용자 서비스에서 사용자 존재 여부를 확인 후,
    중복되지 않는 경우에만 DB에 사용자 등록.

    Args:
        user_in (UserCreate): 사용자 생성에 필요한 정보.
        db (AsyncSession): 데이터베이스 세션.
        client (AsyncClient): 비동기 HTTP 클라이언트.
    """
    try:
        await get_user_info(user_in.id, client)
    except HTTPException as e:
        if e.status_code == Config.HttpStatus.NOT_FOUND:
            raise HTTPException(
                status_code=Config.HttpStatus.NOT_FOUND,
                detail="User not found in User service",
            ) from e
        raise e

    result = await db.execute(select(User).where(User.id == user_in.id))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=Config.HttpStatus.CONFLICT,
            detail="User already exists",
        )

    user = User(**user_in.model_dump())
    db.add(user)
    try:
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="Database commit failed",
        ) from e
    await db.refresh(user)
    return user


@user_router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    """Get a user by ID."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=Config.HttpStatus.NOT_FOUND, detail="User not found"
        )
    return user


@user_router.get("/", response_model=list[UserRead])
async def list_users(db: Annotated[AsyncSession, Depends(get_db)]):
    """List all users."""
    result = await db.execute(select(User))
    return result.scalars().all()


@user_router.delete("/{user_id}", status_code=Config.HttpStatus.NO_CONTENT)
async def delete_user(user_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    """Delete a user by ID."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=Config.HttpStatus.NOT_FOUND, detail="User not found"
        )
    await db.delete(user)
    try:
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="Database commit failed",
        ) from e
