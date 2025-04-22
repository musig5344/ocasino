from typing import Generator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db as get_db_session

async def get_db() -> Generator[AsyncSession, None, None]:
    """
    데이터베이스 세션 의존성
    
    Yields:
        AsyncSession: 데이터베이스 세션
    """
    async with get_db_session() as session:
        yield session