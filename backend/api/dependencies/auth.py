from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from typing import Dict, Any, List, Optional
from uuid import UUID
import logging

from backend.db.database import get_db
from backend.services.auth.auth_service import AuthService
from backend.utils.request_context import get_request_attribute
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from backend.core.dependencies import get_db as db_get_db # 경로 수정
# from backend.api.dependencies.cache import get_redis_client # 이전 임포트 주석 처리
from backend.cache.redis_cache import get_redis_client # 수정된 임포트 경로
from redis.asyncio import Redis # 타입 힌팅용
# from backend.services.auth.exceptions import AuthenticationError # 이전 임포트 주석 처리
from backend.core.exceptions import AuthenticationError # 수정된 임포트 경로

logger = logging.getLogger(__name__)

# API 키 헤더 정의
API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

# get_auth_service 함수 정의
def get_auth_service(
    db: AsyncSession = Depends(db_get_db),
    redis_client: Redis = Depends(get_redis_client)
) -> AuthService:
    """AuthService 의존성 주입 함수"""
    return AuthService(db=db, redis_client=redis_client)