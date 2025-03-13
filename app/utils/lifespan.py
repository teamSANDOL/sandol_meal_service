"""DB의 meal_type 테이블을 meal_types.json과 동기화"""
import traceback

from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select
from sqlalchemy import func

from app.database import AsyncSessionLocal
from app.models.meals import MealType
from app.models.user import User
from app.config import Config, logger


async def sync_meal_types():
    """DB의 meal_type 테이블을 meal_types.json과 동기화

    meal_types.json 파일에 정의된 meal_type들을 데이터베이스의 meal_type 테이블과 동기화합니다.
    기존에 존재하지 않는 meal_type은 새로 추가됩니다.

    Raises:
        IntegrityError: 중복된 meal_type이 감지된 경우 발생합니다.
    """
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


async def sync_test_users():
    """DEBUG 모드일 때, 최소 2명의 test_user를 유지하도록 동기화

    DEBUG 모드가 활성화된 경우, 데이터베이스에 최소 2명의 test_user가 존재하도록 동기화합니다.
    부족한 사용자 수만큼 새로운 test_user를 추가합니다.

    Raises:
        IntegrityError: 중복된 test_user가 감지된 경우 발생합니다.
    """
    if not Config.debug:
        return  # debug 모드가 아니면 실행하지 않음

    async with AsyncSessionLocal() as db:
        try:
            # 현재 사용자 수 확인
            user_count_result = await db.execute(select(func.count(User.id)))
            user_count = user_count_result.scalar_one()  # scalar() 대신 scalar_one() 사용

            if user_count < Config.MIN_TEST_USERS:
                new_users = [
                    User()
                    for i in range(2 - user_count)
                ]
                db.add_all(new_users)
                await db.commit()
                logger.info("DEBUG 모드 활성화: 임의 사용자 %s명 추가됨", len(new_users))
            else:
                logger.debug("DEBUG 모드 활성화: 사용자 수 충분함")

        except IntegrityError:
            message = traceback.format_exc()
            logger.debug("Error details: %s", message)
            logger.warning("중복된 test_user가 감지되었습니다.")
            await db.rollback()
            logger.debug("DB 롤백 완료")
