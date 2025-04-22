from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from typing import Optional
import logging

from backend.core.config import settings
from backend.services.auth.api_key_service import AuthenticationService
from backend.db.database import SessionLocal

logger = logging.getLogger(__name__)

class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """
    IP 화이트리스트 미들웨어
    
    API 키가 있는 요청의 경우 해당 API 키에 대한 IP 화이트리스트를 검증합니다.
    """
    
    async def dispatch(self, request: Request, call_next):
        """
        미들웨어 분배 함수
        
        Args:
            request: 요청 객체
            call_next: 다음 미들웨어 호출 함수
            
        Returns:
            응답 객체
        """
        # IP 화이트리스팅이 비활성화된 경우 건너뛰기
        if not settings.ENABLE_IP_WHITELIST:
            return await call_next(request)
        
        # 화이트리스트 예외 경로 확인
        if self._is_whitelisted_path(request.url.path):
            return await call_next(request)
        
        # API 키 가져오기
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            # API 키가 없으면 다음 미들웨어로 계속 진행
            # (인증 미들웨어에서 처리됨)
            return await call_next(request)
        
        # 현재 IP 가져오기
        ip_address = self._get_client_ip(request)
        
        # IP 화이트리스트 확인
        is_whitelisted = await self._check_ip_whitelist(api_key, ip_address)
        if not is_whitelisted:
            logger.warning(f"IP not whitelisted: {ip_address} for API key {api_key[:5]}...")
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": f"IP address {ip_address} is not whitelisted"
                    }
                }
            )
        
        # 화이트리스트 확인 통과
        return await call_next(request)
    
    def _is_whitelisted_path(self, path: str) -> bool:
        """
        화이트리스트 예외 경로 확인
        
        Args:
            path: 요청 경로
            
        Returns:
            bool: 화이트리스트 예외 여부
        """
        # 화이트리스트 예외 경로 목록
        whitelisted_paths = [
            "/api/health",
            "/docs",
            "/redoc",
            "/openapi.json"
        ]
        
        return any(path.startswith(wl_path) for wl_path in whitelisted_paths)
    
    def _get_client_ip(self, request: Request) -> str:
        """
        클라이언트 IP 주소 가져오기
        
        Args:
            request: 요청 객체
            
        Returns:
            str: IP 주소
        """
        # X-Forwarded-For 헤더를 확인 (프록시 뒤에 있는 경우)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # 첫 번째 IP만 사용 (쉼표로 구분된 목록일 수 있음)
            return forwarded_for.split(",")[0].strip()
        
        # 클라이언트 호스트 사용
        return request.client.host
    
    async def _check_ip_whitelist(self, api_key: str, ip_address: str) -> bool:
        """
        IP 화이트리스트 확인
        
        Args:
            api_key: API 키
            ip_address: IP 주소
            
        Returns:
            bool: 화이트리스트 여부
        """
        try:
            # DB 세션 생성
            db = SessionLocal()
            
            try:
                # 인증 서비스 생성
                auth_service = AuthenticationService(db)
                
                # API 키 정보 가져오기
                api_key_info = await auth_service.get_api_key_info(api_key)
                if not api_key_info:
                    return False
                
                # IP 화이트리스트 확인
                return await auth_service.check_ip_whitelist(
                    api_key_info["partner_key_id"],
                    ip_address
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error checking IP whitelist: {e}")
            # 오류 발생 시 안전하게 거부
            return False