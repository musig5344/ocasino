from fastapi import Request, HTTPException, status
from typing import Optional, Dict, Any, Callable
import logging
from datetime import datetime

from backend.core.config import settings
from backend.services.auth.auth_service import AuthService
from backend.db.database import get_db
from backend.utils.request_context import get_request_context, set_request_attribute

logger = logging.getLogger(__name__)

class AuthMiddleware:
    """
    API 인증 미들웨어
    
    모든 요청에 대해 API 키를 검증하고 IP 화이트리스트를 확인합니다.
    """
    
    async def __call__(self, request: Request, call_next: Callable):
        """미들웨어 처리 로직"""
        # 헬스 체크 및 문서 URL은 인증에서 제외
        if self._is_exempted_path(request.url.path):
            return await call_next(request)
        
        # API 키 추출
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            logger.warning(f"API key missing for request to {request.url.path}")
            return self._unauthorized_response("API key is required")
        
        try:
            # DB 세션 생성 및 인증 서비스 초기화
            async with get_db() as db:
                auth_service = AuthService(db)
                
                # API 키 인증
                api_key_info = await auth_service.authenticate_api_key(api_key)
                if not api_key_info:
                    logger.warning(f"Invalid API key: {api_key[:5]}... for request to {request.url.path}")
                    return self._unauthorized_response("Invalid API key")
                
                # 요청 컨텍스트에 파트너 정보 저장
                set_request_attribute("partner_id", api_key_info["partner_id"])
                set_request_attribute("permissions", api_key_info["permissions"])
                set_request_attribute("api_key_id", api_key_info["api_key_id"])
                
                # IP 화이트리스트 확인 (활성화된 경우)
                if settings.ENABLE_IP_WHITELIST:
                    client_ip = self._get_client_ip(request)
                    is_allowed = await auth_service.check_ip_whitelist(
                        api_key_info["api_key_id"], client_ip
                    )
                    
                    if not is_allowed:
                        logger.warning(f"IP not allowed: {client_ip} for partner {api_key_info['partner_id']}")
                        return self._forbidden_response(f"IP address {client_ip} is not whitelisted")
                
                # 마지막 사용 시간 업데이트 (비동기 처리)
                await auth_service.update_api_key_last_used(api_key, self._get_client_ip(request))
        
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return self._server_error_response("Authentication service error")
        
        # 인증 성공, 다음 미들웨어 호출
        return await call_next(request)
    
    def _is_exempted_path(self, path: str) -> bool:
        """인증 면제 경로 확인"""
        exempted_paths = [
            "/api/health",
            "/docs",
            "/redoc",
            "/openapi.json"
        ]
        return any(path.startswith(exempt_path) for exempt_path in exempted_paths)
    
    def _get_client_ip(self, request: Request) -> str:
        """클라이언트 IP 주소 가져오기"""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # 첫 번째 IP만 사용 (쉼표로 구분된 목록일 수 있음)
            return forwarded_for.split(",")[0].strip()
        
        # 클라이언트 호스트 사용
        return request.client.host
    
    def _unauthorized_response(self, detail: str):
        """401 Unauthorized 응답 생성"""
        return self._error_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="UNAUTHORIZED",
            message=detail,
            headers={"WWW-Authenticate": "APIKey"}
        )
    
    def _forbidden_response(self, detail: str):
        """403 Forbidden 응답 생성"""
        return self._error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="FORBIDDEN",
            message=detail
        )
    
    def _server_error_response(self, detail: str):
        """500 Internal Server Error 응답 생성"""
        return self._error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="INTERNAL_ERROR",
            message=detail
        )
    
    def _error_response(self, status_code: int, error_code: str, message: str, headers: Optional[Dict[str, str]] = None):
        """표준화된 오류 응답 생성"""
        from fastapi.responses import JSONResponse
        
        content = {
            "error": {
                "code": error_code,
                "message": message,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        
        return JSONResponse(
            status_code=status_code,
            content=content,
            headers=headers or {}
        )