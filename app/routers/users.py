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

from app.config.config import Config, logger
from app.models.user import User
from app.schemas.users import UserRead, UserSchema
from app.utils.db import get_db, get_user_by_id, create_user, delete_user
from app.services.user_service import keycloak_user_exists_by_id

router = APIRouter(prefix="/users", tags=["User"])


@router.post("/", response_model=UserRead)
async def register_user(
    user_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """사용자를 등록합니다.

    외부 사용자 서비스에서 사용자 존재 여부를 확인 후,
    중복되지 않는 경우에만 DB에 사용자 등록.

    Args:
        user_id (str): 사용자 ID.
        db (AsyncSession): 데이터베이스 세션.
    """
    try:
        existence_on_db = await get_user_by_id(db, user_id)
    except SQLAlchemyError as e:
        logger.error("데이터베이스 조회 중 오류 발생: %s", e)
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="Database query failed",
        ) from e
    if existence_on_db:
        raise HTTPException(
            status_code=Config.HttpStatus.CONFLICT,
            detail="User already exists in database",
        )
    try:
        existence = await keycloak_user_exists_by_id(user_id)
    except HTTPException as e:
        if e.status_code == Config.HttpStatus.NOT_FOUND:
            raise HTTPException(
                status_code=Config.HttpStatus.NOT_FOUND,
                detail="User not found in User service",
            ) from e
        logger.error("사용자 정보 조회 중 오류 발생: %s", e)
        raise e
    if not existence:
        raise HTTPException(
            status_code=Config.HttpStatus.NOT_FOUND,
            detail="User not found in User service",
        )
    logger.info("Creating user with user_id: %s", user_id)
    return UserSchema.model_validate(await create_user(user_id, db))


@router.get("/{user_id}", response_model=UserSchema)
async def get_user(user_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Get a user by ID."""
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=Config.HttpStatus.NOT_FOUND,
            detail="User not found",
        )
    return UserSchema.model_validate(user)


@router.get("/", response_model=list[UserSchema])
async def list_users(db: Annotated[AsyncSession, Depends(get_db)]):
    """List all users."""
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [UserSchema.model_validate(user) for user in users]

@router.delete("/{user_id:str}", status_code=Config.HttpStatus.NO_CONTENT)
async def remove_user(user_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Delete a user by ID."""
    await delete_user(db, user_id)
    try:
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error("사용자 삭제 중 오류 발생 %s", e)
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="Database commit failed",
        ) from e
