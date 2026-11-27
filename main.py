"""Sandol의 메인 애플리케이션 파일입니다."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from app.config import logger, Config
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.models.restaurants import ServiceAccountNotReadyError
from app.routers import meals_router, restaurants_router, users_router
from app.utils.lifespan import (
    sync_meal_types,
    sync_restaurants,
    complete_deferred_startup,
    ensure_service_account_resilient,
    readiness,
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

    # 3. Service Account를 DB에 등록 (Restaurant owner로 사용)
    #    Keycloak이 응답하지 않아도 기동은 막지 않고, 백그라운드에서 마저 동기화한다.
    deferred_task: asyncio.Task[None] | None = None
    if await ensure_service_account_resilient():
        # 4. Restaurant 동기화
        await sync_restaurants()
    else:
        logger.warning(
            "Keycloak 확인 실패로 service_account 동기화를 백그라운드로 넘깁니다."
        )
        deferred_task = asyncio.create_task(complete_deferred_startup())

    # 5. iBook이 PDF를 제공하므로 기본적으로 엑셀 자동 수집을 비활성화한다.
    scheduler_started = Config.MEAL_EXCEL_AUTO_SYNC_ENABLED
    if scheduler_started:
        start_scheduler()
    else:
        logger.info("[meal_excel_sync] 자동 동기화 비활성화")

    yield  # FastAPI 실행 유지

    # 6. 종료 작업
    if deferred_task is not None:
        deferred_task.cancel()
    if scheduler_started:
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


@app.exception_handler(ServiceAccountNotReadyError)
async def service_account_not_ready_handler(
    _request: Request, _exc: ServiceAccountNotReadyError
) -> JSONResponse:
    """서비스 계정 준비 전 요청에는 503으로 응답합니다."""
    return JSONResponse(
        status_code=503,
        content={"detail": "서비스 계정 준비 중입니다. 잠시 후 다시 시도해주세요."},
    )


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트입니다. 준비 상태는 별도 필드로 보고하고 status는 유지합니다."""
    return {"status": "ok", "service_account_ready": readiness["service_account"]}


if __name__ == "__main__":
    HOST = "0.0.0.0"  # noqa: S104
    PORT = 5600
    logger.info("Starting Sandol server on %s:%s", HOST, PORT)
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
