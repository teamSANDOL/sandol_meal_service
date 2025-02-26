from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import Config

# SQLAlchemy 엔진 생성
engine = create_engine(Config.DATABASE_URL, connect_args={"check_same_thread": False})

# 세션 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base 클래스 생성
Base = declarative_base()

# 데이터베이스 테이블 생성 함수
def init_db():
    """데이터베이스 테이블을 생성합니다."""
    Base.metadata.create_all(bind=engine)
