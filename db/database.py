"""
데이터베이스 연결 및 세션 관리
"""
import logging
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from backend.core.config import settings

logger = logging.getLogger(__name__)

# 비동기 엔진 생성
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True
)

# 세션 생성을 위한 팩토리
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# SQLAlchemy 기본 모델
Base = declarative_base()

# 비동기 DB 세션
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 의존성 주입을 위한 비동기 DB 세션 제공
    """
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Database session error: {e}")
        raise
    finally:
        await session.close()

# 트랜잭션 컨텍스트 매니저
@asynccontextmanager
async def transaction(session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """
    트랜잭션 컨텍스트 매니저
    with 구문과 함께 사용
    """
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise