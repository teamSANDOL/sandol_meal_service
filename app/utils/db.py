"""이 모듈은 데이터베이스 세션과 사용자 인증 및 권한 확인을 위한 유틸리티 함수를 제공합니다."""

from datetime import datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from httpx import AsyncClient
from keycloak import KeycloakAdmin
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload


from app.config import Config, logger
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.restaurants import Restaurant
from app.services.user_service import keycloak_user_exists_by_id, check_admin_user


async def get_db():
    """비동기 데이터베이스 세션을 생성하고 반환합니다.

    Yields:
        AsyncSession: 비동기 데이터베이스 세션 객체
    """
    async with AsyncSessionLocal() as db:
        yield db


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    """주어진 user_id로 사용자를 조회합니다."""
    return await db.scalar(select(User).where(User.id == user_id))


async def create_user(user_id: str, db: AsyncSession, check_existance=True) -> User:
    """사용자를 생성하는 비즈니스 로직.

    사용자가 이미 존재하는지 확인하는 옵션을 포함합니다.
    해당 옵션은 가급적 활성화해야 합니다.

    Args:
        user_id (str): 생성할 계정의 keycloak id
        db (AsyncSession): 비동기 데이터베이스 세션.

    Raises:
        HTTPException: 사용자 정보가 외부 서비스에 존재하지 않거나,
                        이미 존재하는 경우 오류 발생.

    Returns:
        User: 생성된 사용자 객체.
    """
    if check_existance:
        existing = await get_user_by_id(db, user_id)
        if existing:
            raise HTTPException(
                status_code=Config.HttpStatus.CONFLICT,
                detail="User already exists",
            )

    if not await keycloak_user_exists_by_id(user_id):  # 외부 서비스에서 사용자 존재 여부 확인
        raise HTTPException(
            status_code=Config.HttpStatus.NOT_FOUND,
            detail="User not found in User service",
        )

    user = User(user_id=user_id)
    db.add(user)
    try:
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=Config.HttpStatus.INTERNAL_SERVER_ERROR,
            detail="DB Commit Failure",
        ) from e
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: str):
    """사용자를 삭제하고 해당 사용자가 소유한 식당을 소프트 삭제합니다.

    Args:
        db (AsyncSession): 비동기 데이터베이스 세션
        user_id (str): 삭제할 사용자의 ID
    Raises:
        HTTPException: 사용자가 존재하지 않을 경우 404 오류 발생
    """
    stmt = select(User).where(User.user_id == user_id)  # ← DB 컬럼명에 맞게
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")


    result = await db.execute(
        select(Restaurant)
        .options(selectinload(Restaurant.managers))  # managers 미리 로드
        .where(Restaurant.owner == user.id)
    )
    for restaurant in result.scalars():
        restaurant.soft_delete()

    managed = await db.execute(
        select(Restaurant).join(Restaurant.managers).filter(User.id == user.id)
    )
    for restaurant in managed.scalars():
        if user in restaurant.managers:
            restaurant.managers.remove(user)

    # 💡 중간 flush로 관계 정리
    await db.flush()

    await db.delete(user)


async def get_or_create_user(
    user_id: str,
    db: AsyncSession,
) -> User:
    """DB에서 사용자 조회, 없으면 외부에서 받아와 생성"""
    user = await get_user_by_id(db, user_id)
    if user:
        return user

    logger.info("사용자 정보 없음, 사용자 존재 여부 외부 확인", extra={"user_id": user_id})

    return await create_user(user_id, db, check_existance=False)


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_user_id: str = Header(None),
) -> User:
    """X-User-ID 헤더를 가져와 비동기 방식으로 User 객체를 반환합니다.

    Args:
        x_user_id (str): 요청 헤더에서 가져온 사용자 ID
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
    return await get_or_create_user(x_user_id, db)


async def get_admin_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_user_id: str = Header(None),
) -> User:
    """현재 사용자가 관리자 권한을 가지고 있는지 확인하고 UserSchema 객체를 반환합니다.

    Args:
        x_user_id (str): 요청 헤더에서 가져온 사용자 ID
        db (AsyncSession): 비동기 데이터베이스 세션
        client (AsyncClient): 비동기 HTTP 클라이언트

    Returns:
        User: 관리자 권한이 확인된 사용자 DB 객체

    Raises:
        HTTPException: X-User-ID 헤더가 없거나 사용자가 존재하지 않는 경우
    """
    user = await get_current_user(db, x_user_id)
    await check_admin_user(user.user_id)
    return user
