from typing import Generator
from fastapi import Depends
from sqlalchemy.orm import Session

from backend.db.database import SessionLocal

def get_db() -> Generator[Session, None, None]:
    """
    데이터베이스 세션 의존성
    
    Yields:
        Session: 데이터베이스 세션
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()