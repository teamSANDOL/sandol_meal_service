import os
import asyncio
import sys
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import pool
from alembic import context
from dotenv import load_dotenv

# ✅ 환경 변수 로드
load_dotenv()

# ✅ 프로젝트 경로 추가 (어디서든 `app` import 가능)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ✅ 데이터베이스 설정 (없을 경우 에러 발생)
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL 환경 변수가 설정되지 않았습니다.")

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# ✅ Python 로깅 설정
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ✅ SQLAlchemy 모델 자동 감지
from app.database import Base  # Base.metadata 자동 불러오기
from app.models.meals import NonEscapedJSON  # ✅ 커스텀 타입 추가

target_metadata = Base.metadata


# ✅ 커스텀 타입을 자동으로 마이그레이션 파일에 포함하도록 설정
def render_item(type_, obj, autogen_context):
    """Alembic이 마이그레이션 파일을 생성할 때 커스텀 타입을 자동으로 인식"""
    if isinstance(obj, NonEscapedJSON):
        autogen_context.imports.add(
            "from app.models.meals import NonEscapedJSON"
        )  # ✅ 자동 import 추가
        return "NonEscapedJSON()"
    return False  # 기본 동작 유지


# ✅ 비동기 DB 엔진 생성
connectable = create_async_engine(DATABASE_URL, poolclass=pool.NullPool, future=True)


def run_migrations_offline():
    """오프라인 모드에서 마이그레이션 실행"""
    context.configure(
        url=DATABASE_URL,  # ✅ 명확하게 URL을 설정
        target_metadata=target_metadata,
        render_item=render_item,  # ✅ 커스텀 타입 자동 추가
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    """온라인 모드에서 마이그레이션 실행"""
    async with connectable.connect() as connection:
        await connection.run_sync(
            lambda conn: context.configure(
                connection=conn,
                target_metadata=target_metadata,
                render_item=render_item,
            )
        )
        await connection.run_sync(lambda conn: context.run_migrations())


if context.is_offline_mode():
    print("🚀 Running migrations in OFFLINE mode...")
    run_migrations_offline()
else:
    print("🚀 Running migrations in ONLINE mode...")
    asyncio.run(run_migrations_online())
