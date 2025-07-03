"""Sandol의 메인 애플리케이션 파일입니다."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from app.config import logger, Config
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.routers import meals_router, restaurants_router, users_router
from app.utils.lifespan import (
    sync_meal_types,
    sync_test_users,
    set_service_user_as_admin,
    sync_restaurants,
    set_deleted_user,
)
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI의 lifespan 이벤트 핸들러"""
    logger.info("🚀 서비스 시작: 데이터베이스 초기화 및 기본 데이터 동기화")
    logger.debug(
        "Config 정보 로드: %s",
        {
            "debug": Config.debug,
            "timezone": Config.TIMEZONE,
            "database_url": Config.DATABASE_URL,
            "user_service_url": Config.USER_SERVICE_URL,
        },
    )

    # 1. DB 초기화
    await init_db()

    # 2. meal_type 동기화
    await sync_meal_types()

    # 3. Restaurant 동기화
    await sync_restaurants()

    # 4. SERVICE_ID 유저 관리자 권한 설정
    await set_service_user_as_admin()

    # 5. DEBUG 모드일 때 test_user 동기화
    await sync_test_users()

    # 6. 스케줄러 시작
    start_scheduler()

    yield  # FastAPI 실행 유지

    # 7. 종료 작업
    stop_scheduler()
    logger.info("🛑 서비스 종료: 정리 작업 완료")


# lifespan 적용
app = FastAPI(lifespan=lifespan, root_path="/meal")

# 라우터 추가
app.include_router(meals_router)
app.include_router(restaurants_router)
app.include_router(users_router)


@app.get("/")
async def root():
    """루트 엔드포인트입니다."""
    logger.info("Root endpoint accessed")
    return {"test": "Hello Sandol"}


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트입니다."""
    return {"status": "ok"}


if __name__ == "__main__":
    HOST = "0.0.0.0"  # noqa: S104
    PORT = 5600
    logger.info("Starting Sandol server on %s:%s", HOST, PORT)
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
