from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.config import Config
from app.models.user import User
from app.models.restaurants import Restaurant
from app.schemas.users import UserCreate


async def create_user_process(user_in: UserCreate, db: AsyncSession) -> User:
    """사용자를 생성하는 비즈니스 로직.

    Args:
        user_in (UserCreate): 사용자 생성에 필요한 정보.
        db (AsyncSession): 비동기 데이터베이스 세션.

    Raises:
        HTTPException: 사용자 정보가 외부 서비스에 존재하지 않거나,
                          이미 존재하는 경우 오류 발생.

    Returns:
        User: 생성된 사용자 객체.
    """
    existing_user = await db.scalar(select(User).where(User.id == user_in.id))
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
            detail="DB Commit Failure",
        ) from e
    await db.refresh(user)
    return user


async def delete_user_process(session: AsyncSession, user_id: int):
    """사용자를 삭제하고 해당 사용자가 소유한 식당을 소프트 삭제합니다.

    Args:
        session (AsyncSession): 비동기 데이터베이스 세션
        user_id (int): 삭제할 사용자의 ID
    Raises:
        HTTPException: 사용자가 존재하지 않을 경우 404 오류 발생
    """
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=Config.HttpStatus.NOT_FOUND, detail="User not found"
        )

    result = await session.execute(
        select(Restaurant)
        .options(selectinload(Restaurant.managers))  # managers 미리 로드
        .where(Restaurant.owner == user.id)
    )
    for restaurant in result.scalars():
        restaurant.soft_delete()

    managed = await session.execute(
        select(Restaurant).join(Restaurant.managers).filter(User.id == user.id)
    )
    for restaurant in managed.scalars():
        if user in restaurant.managers:
            restaurant.managers.remove(user)

    # 💡 중간 flush로 관계 정리
    await session.flush()

    await session.delete(user)
