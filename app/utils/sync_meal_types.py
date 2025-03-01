"""DB의 meal_type 테이블을 meal_types.json과 동기화"""
import traceback

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select

from app.database import AsyncSessionLocal
from app.models.meals import MealType
from app.config import Config, logger


async def sync_meal_types():
    """DB의 meal_type 테이블을 meal_types.json과 동기화"""
    async with AsyncSessionLocal() as db:
        try:
            meal_types = Config.load_meal_types()

            # 기존 DB에 있는 meal_type 조회 (비동기)
            result = await db.execute(select(MealType))
            existing_meal_types = {mt.name for mt in result.scalars().all()}
            logger.debug("기존 meal_type: %s", existing_meal_types)

            # 추가해야 할 meal_type 찾기
            new_meal_types = [
                MealType(name=mt) for mt in meal_types if mt not in existing_meal_types
            ]
            logger.debug("새로 추가할 meal_type: %s", [mt.name for mt in new_meal_types])

            if new_meal_types:
                db.add_all(new_meal_types)  # ✅ `bulk_save_objects()` 대신 `add_all()` 사용
                await db.commit()
                logger.info("%s개의 meal_type이 추가되었습니다.", len(new_meal_types))
            else:
                logger.info("meal_type이 최신 상태입니다.")

        except IntegrityError:
            message = traceback.format_exc()
            logger.debug("Error details: %s", message)
            logger.warning("중복된 meal_type이 감지되었습니다.")
            await db.rollback()
            logger.debug("DB 롤백 완료")
