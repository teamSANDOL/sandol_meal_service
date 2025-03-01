from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from httpx import AsyncClient

from app.database import AsyncSessionLocal
from app.models import User  # User 모델이 models 디렉토리에 있다고 가정
from app.schemas.restaurants import UserSchema
from app.config import Config


async def get_db():
    async with AsyncSessionLocal() as db:
        yield db


async def get_current_user(
    x_user_id: int = Header(None), db: AsyncSession = Depends(get_db)
) -> User:
    """X-User-ID 헤더를 가져와 비동기 방식으로 User 객체 반환"""
    if x_user_id is None:
        raise HTTPException(status_code=401, detail="X-User-ID 헤더가 필요합니다.")

    result = await db.execute(select(User).filter(User.id == x_user_id))
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="해당 사용자가 존재하지 않습니다.")

    return user


async def get_user_info(
    user_id: int, client: AsyncClient = Depends(AsyncClient)
) -> UserSchema:
    """사용자 정보를 가져와 User 객체 반환"""
    response = await client.get(f"{Config.USER_SERVICE_URL}/users/{user_id}")
    response.raise_for_status()
    return UserSchema.model_validate(response.json(), strict=False)


async def check_admin_user(user: UserSchema = Depends(get_current_user)) -> UserSchema:
    """관리자 사용자인지 확인"""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user


async def get_admin_user(
    x_user_id: int = Header(None),
    db: AsyncSession = Depends(get_db),
    client: AsyncClient = Depends(AsyncClient),
) -> UserSchema:
    """현재 사용자가 관리자 권한을 가지고 있는지 확인하고 UserSchema 반환"""
    user = await get_current_user(x_user_id, db)
    user_info = await get_user_info(user.id, client)
    admin_user = check_admin_user(user_info)
    return admin_user
