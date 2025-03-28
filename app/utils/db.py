"""이 모듈은 데이터베이스 세션과 사용자 인증 및 권한 확인을 위한 유틸리티 함수를 제공합니다."""

from datetime import datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import Config
from app.database import AsyncSessionLocal
from app.models.user import User  # User 모델이 models 디렉토리에 있다고 가정
from app.schemas.restaurants import UserSchema
from app.utils.http import get_async_client


async def get_db():
    """비동기 데이터베이스 세션을 생성하고 반환합니다.

    Yields:
        AsyncSession: 비동기 데이터베이스 세션 객체
    """
    async with AsyncSessionLocal() as db:
        yield db


async def get_or_create_user(
    user_id: int,
    db: AsyncSession,
    client: AsyncClient,
) -> User:
    """DB에서 사용자 조회, 없으면 외부에서 받아와 생성"""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()
    if user:
        return user

    try:
        user_info: UserSchema = await get_user_info(user_id, client)
        user = User(id=user_info.id)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user
    except IntegrityError as e:
        await db.rollback()
        # 다른 트랜잭션에서 먼저 추가되었을 수 있음 → 재조회
        result = await db.execute(select(User).filter(User.id == user_id))
        user = result.scalars().first()
        if user:
            return user
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="사용자 추가 중 예외 발생",
        ) from e
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    client: Annotated[AsyncClient, Depends(get_async_client)],
    x_user_id: int = Header(None),
) -> User:
    """X-User-ID 헤더를 가져와 비동기 방식으로 User 객체를 반환합니다.

    Args:
        x_user_id (int): 요청 헤더에서 가져온 사용자 ID
        db (AsyncSession): 비동기 데이터베이스 세션
        client: AsyncClient: 비동기 HTTP 클라이언트

    Returns:
        User: 데이터베이스에서 조회된 사용자 객체

    Raises:
        HTTPException: X-User-ID 헤더가 없거나 사용자가 존재하지 않는 경우
    """
    if x_user_id is None:
        raise HTTPException(
            status_code=Config.HttpStatus.UNAUTHORIZED,
            detail="X-User-ID 헤더가 필요합니다.",
        )
    return await get_or_create_user(x_user_id, db, client)


async def get_user_info(
    user_id: int,
    client: AsyncClient,
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
    if Config.debug and user_id == 1:  # noqa: PLR2004
        return UserSchema(
            id=1,
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
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e
    return UserSchema.model_validate(response.json(), strict=False)


async def is_global_admin(user_id: int, client: AsyncClient) -> bool:
    """User API 서버에 요청하여 global_admin 여부 확인"""
    if Config.debug:
        return user_id == 1
    response = await client.get(
        f"http://user-api-service/users/{user_id}/is_global_admin"
    )

    try:
        response.raise_for_status()
    except Exception as e:
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e

    return response.json().get("is_global_admin", False)


async def check_admin_user(
    user: User,
    client: AsyncClient,
) -> bool:
    """사용자가 관리자 권한을 가지고 있는지 확인합니다.

    Args:
        user (UserSchema): 사용자 정보가 담긴 스키마 객체
        client (AsyncClient): 비동기 HTTP

    Returns:
        bool: 관리자 권한 여부

    Raises:
        HTTPException: 사용자가 관리자 권한이 없는 경우
    """
    if user.meal_admin or await is_global_admin(user.id, client):
        return True
    raise HTTPException(
        status_code=Config.HttpStatus.FORBIDDEN, detail="관리자 권한이 필요합니다."
    )


async def get_admin_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    client: Annotated[AsyncClient, Depends(get_async_client)],
    x_user_id: int = Header(None),
) -> User:
    """현재 사용자가 관리자 권한을 가지고 있는지 확인하고 UserSchema 객체를 반환합니다.

    Args:
        x_user_id (int): 요청 헤더에서 가져온 사용자 ID
        db (AsyncSession): 비동기 데이터베이스 세션
        client (AsyncClient): 비동기 HTTP 클라이언트

    Returns:
        User: 관리자 권한이 확인된 사용자 DB 객체

    Raises:
        HTTPException: X-User-ID 헤더가 없거나 사용자가 존재하지 않는 경우
    """
    user = await get_current_user(db, client, x_user_id)
    await check_admin_user(user, client)
    return user
