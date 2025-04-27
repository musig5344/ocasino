from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from typing import Optional, Dict, Any, Callable, List
import logging
from datetime import datetime

from backend.core.config import settings
from backend.services.auth.auth_service import AuthService
from backend.db.database import get_db, read_session_factory
from backend.utils.request_context import get_request_context, set_request_attribute
from backend.cache.redis_cache import get_redis_client

logger = logging.getLogger(__name__)

class AuthMiddleware(BaseHTTPMiddleware):
    """
    API 키 기반 인증 및 권한 부여 미들웨어
    
    요청 헤더에서 API 키를 추출하고 유효성을 검사합니다.
    유효한 경우, 관련 파트너 정보와 권한을 요청 상태(request.state)에 저장합니다.
    IP 화이트리스트 검사도 수행합니다.
    """
    def __init__(self, app: ASGIApp, exclude_paths: Optional[List[str]] = None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or settings.AUTH_EXCLUDE_PATHS

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """요청 처리 및 인증/권한 부여 수행"""
        
        if request.url.path in self.exclude_paths:
            return await call_next(request)
            
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key required"
            )
            
        async with read_session_factory() as session:
            redis_client = await get_redis_client()
            if not redis_client:
                logger.error("Failed to get Redis client for authentication.")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Cannot connect to authentication cache service."
                )
            
            auth_service = AuthService(session, redis_client)
            try:
                partner, permissions, api_key_id = await auth_service.authenticate_api_key(api_key)
                
                if not partner:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or inactive API Key"
                    )
                
                client_ip = request.client.host if request.client else None
                if not await auth_service.verify_ip_whitelist(partner.id, client_ip):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"IP address {client_ip} not allowed"
                    )
                
                request.state.is_authenticated = True
                request.state.partner_id = partner.id
                request.state.partner_code = partner.code
                request.state.permissions = permissions
                request.state.api_key_id = api_key_id
                
            except HTTPException as e:
                 raise e
            except Exception as e:
                 logger.error(f"Authentication error: {e}", exc_info=True)
                 raise HTTPException(
                     status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                     detail="An internal error occurred during authentication."
                 )

        response = await call_next(request)
        return response