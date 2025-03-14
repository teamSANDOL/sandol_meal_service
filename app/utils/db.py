"""이 모듈은 데이터베이스 세션과 사용자 인증 및 권한 확인을 위한 유틸리티 함수를 제공합니다."""
from datetime import datetime

from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from httpx import AsyncClient
from typing import Annotated

from app.database import AsyncSessionLocal
from app.models.user import User  # User 모델이 models 디렉토리에 있다고 가정
from app.schemas.restaurants import UserSchema
from app.config import Config
from app.utils.http import get_async_client


async def get_db():
    """비동기 데이터베이스 세션을 생성하고 반환합니다.

    Yields:
        AsyncSession: 비동기 데이터베이스 세션 객체
    """
    async with AsyncSessionLocal() as db:
        yield db


async def get_current_user(
    x_user_id: Annotated[int, Header(None)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """X-User-ID 헤더를 가져와 비동기 방식으로 User 객체를 반환합니다.

    Args:
        x_user_id (int): 요청 헤더에서 가져온 사용자 ID
        db (AsyncSession): 비동기 데이터베이스 세션

    Returns:
        User: 데이터베이스에서 조회된 사용자 객체

    Raises:
        HTTPException: X-User-ID 헤더가 없거나 사용자가 존재하지 않는 경우
    """
    if x_user_id is None:
        raise HTTPException(status_code=Config.HttpStatus.UNAUTHORIZED, detail="X-User-ID 헤더가 필요합니다.")

    result = await db.execute(select(User).filter(User.id == x_user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=Config.HttpStatus.FORBIDDEN, detail="해당 사용자가 존재하지 않습니다.")

    return user


async def get_user_info(
    user_id: int, client: Annotated[AsyncClient, Depends(get_async_client)]
) -> UserSchema:
    """사용자 정보를 가져와 UserSchema 객체를 반환합니다.

    Args:
        user_id (int): 사용자 ID
        client (AsyncClient): 비동기 HTTP 클라이언트

    Returns:
        UserSchema: 사용자 정보가 담긴 스키마 객체

    Raises:
        HTTPException: 사용자 정보 조회 실패 시
    """
    if Config.debug:
        return UserSchema(
            id=2,
            is_admin=True,
            name="테스트 사용자",
            email="ident@example.com",
            created_at=datetime.fromisoformat("2021-08-01T00:00:00"),
            updated_at=datetime.fromisoformat("2021-08-01T00:00:00"),
        )
    response = await client.get(f"{Config.USER_SERVICE_URL}/users/{user_id}")
    try:
        response.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR, detail=str(e)) from e
    return UserSchema.model_validate(response.json(), strict=False)

async def is_global_admin(user_id: int, client: Annotated[AsyncClient, Depends(get_async_client)]) -> bool:
    """User API 서버에 요청하여 global_admin 여부 확인"""
    response = await client.get(f"http://user-api-service/users/{user_id}/is_global_admin")

    try:
        response.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR, detail=str(e)) from e

    return response.json().get("is_global_admin", False)

async def check_admin_user(
    user: Annotated[User, Depends(get_current_user)],
    client: Annotated[AsyncClient, Depends(get_async_client)],
) -> bool:
    """사용자가 관리자 권한을 가지고 있는지 확인합니다.

    Args:
        user (UserSchema): 사용자 정보가 담긴 스키마 객체
        client (AsyncClient): 비동기 HTTP

    Returns:
        UserSchema: 관리자 권한이 확인된 사용자 스키마 객체

    Raises:
        HTTPException: 사용자가 관리자 권한이 없는 경우
    """
    if user.meal_admin or await is_global_admin(user.id, client):
        return True
    raise HTTPException(status_code=Config.HttpStatus.FORBIDDEN, detail="관리자 권한이 필요합니다.")


async def get_admin_user(
    x_user_id: Annotated[int, Header(None)],
    db: Annotated[AsyncSession, Depends(get_db)],
    client: Annotated[AsyncClient, Depends(get_async_client)],
) -> UserSchema:
    """현재 사용자가 관리자 권한을 가지고 있는지 확인하고 UserSchema 객체를 반환합니다.

    Args:
        x_user_id (int): 요청 헤더에서 가져온 사용자 ID
        db (AsyncSession): 비동기 데이터베이스 세션
        client (AsyncClient): 비동기 HTTP 클라이언트

    Returns:
        UserSchema: 관리자 권한이 확인된 사용자 스키마 객체

    Raises:
        HTTPException: X-User-ID 헤더가 없거나 사용자가 존재하지 않는 경우
    """
    user = await get_current_user(x_user_id, db)
    await check_admin_user(user, client)
    return user
