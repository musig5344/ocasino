from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
import logging

# Import core dependencies
from backend.core.dependencies import get_db, get_redis_client

# Import auth specific services
from backend.services.auth.auth_service import AuthService
from backend.services.auth.api_key_service import APIKeyService

logger = logging.getLogger(__name__)


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    """AuthService 의존성 주입 함수"""
    # Note: The original dependency used db_get_db which was an alias for get_db
    # from backend.api.dependencies.db. We now use get_db from core directly.
    # The original also imported get_redis_client from backend.cache.redis_cache
    # We now use get_redis from core dependencies.
    return AuthService(db=db)


def get_api_key_service(db: AsyncSession = Depends(get_db), auth_service: AuthService = Depends(get_auth_service)) -> APIKeyService:
    """APIKeyService 의존성 주입 함수"""
    # This service depends on another service (AuthService), which is resolved via Depends.
    return APIKeyService(db=db, auth_service=auth_service) 