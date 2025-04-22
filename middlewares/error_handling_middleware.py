from fastapi import Request, Response
from fastapi.responses import JSONResponse
from typing import Callable, Dict, Any, Optional
import logging
import traceback
from datetime import datetime

from backend.core.config import settings
from backend.api.errors.exceptions import BaseAPIException

logger = logging.getLogger(__name__)

class ErrorHandlingMiddleware:
    """
    전역 예외 처리 미들웨어
    
    모든 처리되지 않은 예외를 잡아 표준화된 응답 형식으로 반환합니다.
    """
    
    async def __call__(self, request: Request, call_next: Callable):
        """미들웨어 처리 로직"""
        try:
            # 요청 처리
            return await call_next(request)
        except BaseAPIException as exc:
            # 이미 정의된 API 예외
            return self._create_error_response(
                status_code=exc.status_code,
                error_code=exc.error_code,
                message=exc.detail,
                headers=exc.headers
            )
        except Exception as exc:
            # 처리되지 않은 예외
            logger.error(f"Unhandled exception: {exc}", exc_info=True)
            
            # 개발 환경에서만 자세한 오류 정보 제공
            message = "Internal server error"
            details = None
            
            if settings.DEBUG:
                message = str(exc)
                details = traceback.format_exc()
            
            return self._create_error_response(
                status_code=500,
                error_code="INTERNAL_ERROR",
                message=message,
                details=details
            )
    
    def _create_error_response(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None
    ):
        """표준화된 오류 응답 생성"""
        content = {
            "error": {
                "code": error_code,
                "message": message,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        
        if details and settings.DEBUG:
            content["error"]["details"] = details
        
        return JSONResponse(
            status_code=status_code,
            content=content,
            headers=headers or {}
        )