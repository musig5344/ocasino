from typing import AsyncGenerator, Generator, Tuple
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_read_db, get_write_db, get_db as get_db_session

# get_db 함수는 backend.core.dependencies 로 이동되었으므로 여기서 삭제
# async def get_db() -> AsyncGenerator[AsyncSession, None]: 
#     """
#     데이터베이스 세션 의존성 (읽기/쓰기 분리 미적용 시 기본 세션)
#     """
#     async for session in get_db_session():
#         yield session

# --- 읽기/쓰기 분리를 위한 의존성 함수들 --- (이들은 아직 사용될 수 있으므로 유지)

async def get_read_session() -> AsyncGenerator[AsyncSession, None]: # AsyncGenerator 사용
    """읽기 전용 DB 세션 의존성"""
    async for session in get_read_db():
        yield session

async def get_write_session() -> AsyncGenerator[AsyncSession, None]: # AsyncGenerator 사용
    """쓰기 전용 DB 세션 의존성"""
    async for session in get_write_db():
        yield session

async def get_sessions() -> Generator[Tuple[AsyncSession, AsyncSession], None, None]:
    """읽기 및 쓰기 세션 의존성"""
    read_session = None
    write_session = None
    
    read_db_gen = get_read_db()
    write_db_gen = get_write_db()
    
    try:
        # 비동기 제너레이터에서 첫 항목(세션) 가져오기
        read_session = await read_db_gen.__anext__()
        write_session = await write_db_gen.__anext__()
            
        yield (read_session, write_session)
        
    finally:
        # 제너레이터 종료 처리 (세션 close는 database.py에서 처리됨)
        try:
            await read_db_gen.aclose() # 비동기 제너레이터 종료
        except StopAsyncIteration:
            pass # 이미 종료됨
        except Exception as e:
             # 로깅 추가 권장
             print(f"Error closing read session generator: {e}")
        
        try:
            await write_db_gen.aclose() # 비동기 제너레이터 종료
        except StopAsyncIteration:
            pass # 이미 종료됨
        except Exception as e:
            # 로깅 추가 권장
            print(f"Error closing write session generator: {e}")