"""Sandol의 메인 애플리케이션 파일입니다."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
import uvicorn

from app.config.config import logger
from app.routers import meals_router, restaurants_router
from app.utils.sync_meal_types import sync_meal_types
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI의 lifespan 이벤트 핸들러"""
    logger.info("🚀 서비스 시작: 데이터베이스 초기화 및 meal_types 동기화")

    # 애플리케이션 시작 시 데이터베이스 테이블 생성
    await init_db()

    # 서버 시작 시 meal_type 동기화 실행
    await sync_meal_types()

    yield  # FastAPI가 실행 중인 동안 유지됨

    # 애플리케이션 종료 시 로그 출력
    logger.info("🛑 서비스 종료: 정리 작업 완료")


# lifespan 적용
app = FastAPI(lifespan=lifespan, root_path="/meal_service")

# 라우터 추가
app.include_router(meals_router)
app.include_router(restaurants_router)


@app.get("/")
async def root():
    """루트 엔드포인트입니다."""
    logger.info("Root endpoint accessed")
    return {"test": "Hello Sandol"}


if __name__ == "__main__":
    HOST = "0.0.0.0"
    PORT = 5600

    logger.info("Starting Sandol server on %s:%s", HOST, PORT)
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
