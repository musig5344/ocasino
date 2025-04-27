"""
데이터베이스 연결 및 세션 관리
"""
import logging
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

from backend.core.config import settings

logger = logging.getLogger(__name__)

# 읽기 전용 및 쓰기 전용 엔진 생성 (URL 통합 및 없는 설정 제거)
read_engine = create_async_engine(
    str(settings.SQLALCHEMY_DATABASE_URI), # URL 통합 및 문자열 변환
    # echo=settings.DB_ECHO, # 존재하지 않는 설정 제거
    # pool_size=settings.DB_READ_POOL_SIZE, # 존재하지 않는 설정 제거
    # max_overflow=settings.DB_READ_MAX_OVERFLOW, # 존재하지 않는 설정 제거
    pool_pre_ping=True,
    pool_timeout=30,  # 풀 타임아웃 추가
    pool_recycle=1800 # 풀 재활용 시간 추가
)

write_engine = create_async_engine(
    str(settings.SQLALCHEMY_DATABASE_URI), # URL 통합 및 문자열 변환
    # echo=settings.DB_ECHO, # 존재하지 않는 설정 제거
    # pool_size=settings.DB_WRITE_POOL_SIZE, # 존재하지 않는 설정 제거
    # max_overflow=settings.DB_WRITE_MAX_OVERFLOW, # 존재하지 않는 설정 제거
    pool_pre_ping=True,
    pool_timeout=30,  # 풀 타임아웃 추가
    pool_recycle=1800 # 풀 재활용 시간 추가
)

# 세션 팩토리 생성 (기존 단일 팩토리 제거)
read_session_factory = async_sessionmaker(
    read_engine, expire_on_commit=False, class_=AsyncSession
)
write_session_factory = async_sessionmaker(
    write_engine, expire_on_commit=False, class_=AsyncSession
)

# SQLAlchemy 기본 모델
Base = declarative_base()

async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    """읽기 전용 DB 세션 제공"""
    session = read_session_factory()
    try:
        yield session
    finally:
        await session.close()

async def get_write_db() -> AsyncGenerator[AsyncSession, None]:
    """쓰기 전용 DB 세션 제공"""
    session = write_session_factory()
    try:
        yield session
        # 쓰기 세션은 사용 후 커밋
        await session.commit() 
    except Exception:
        # 오류 발생 시 롤백
        await session.rollback()
        raise
    finally:
        await session.close()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """하위 호환성을 위한 기본 DB 세션 제공 (쓰기 세션 반환)"""
    async for session in get_write_db():
        yield session

@asynccontextmanager
async def db_context() -> AsyncGenerator[tuple[AsyncSession, AsyncSession], None]:
    """읽기 및 쓰기 세션을 함께 제공하는 컨텍스트 매니저"""
    read_session = read_session_factory()
    write_session = write_session_factory()
    try:
        yield (read_session, write_session)
        # 컨텍스트 종료 시 쓰기 세션 커밋
        await write_session.commit() 
    except Exception:
        # 오류 시 롤백
        await write_session.rollback()
        raise
    finally:
        # 모든 세션 닫기
        await read_session.close()
        await write_session.close()

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