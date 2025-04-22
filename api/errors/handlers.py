from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from typing import Union, Dict, Any
import logging
import traceback
from datetime import datetime

from backend.api.errors.exceptions import BaseAPIException
from backend.core.config import settings

logger = logging.getLogger(__name__)

def register_exception_handlers(app: FastAPI) -> None:
    """
    애플리케이션에 예외 핸들러 등록
    
    Args:
        app: FastAPI 애플리케이션 인스턴스
    """
    @app.exception_handler(BaseAPIException)
    async def handle_base_api_exception(request: Request, exc: BaseAPIException) -> JSONResponse:
        """API 예외 핸들러"""
        # 에러 로깅
        logger.error(f"API Exception: {exc.error_code} - {exc.detail}")
        
        return create_error_response(
            status_code=exc.status_code,
            error_code=exc.error_code,
            message=exc.detail,
            headers=exc.headers
        )
    
    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """요청 유효성 검사 오류 핸들러"""
        # 에러 로깅
        logger.warning(f"Validation error: {exc.errors()}")
        
        # 사용자 친화적인 오류 메시지 생성
        error_messages = []
        for error in exc.errors():
            loc = " -> ".join(str(x) for x in error["loc"])
            msg = error["msg"]
            error_messages.append(f"{loc}: {msg}")
        
        return create_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="VALIDATION_ERROR",
            message="Invalid request data",
            details=error_messages
        )
    
    @app.exception_handler(SQLAlchemyError)
    async def handle_sqlalchemy_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        """데이터베이스 오류 핸들러"""
        # 상세 에러 로깅 (개발 환경에서만)
        error_details = str(exc)
        if settings.DEBUG:
            error_details = traceback.format_exc()
        
        logger.error(f"Database error: {error_details}")
        
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="DATABASE_ERROR",
            message="Database operation failed"
        )
    
    @app.exception_handler(Exception)
    async def handle_general_exception(request: Request, exc: Exception) -> JSONResponse:
        """일반 예외 핸들러"""
        # 상세 에러 로깅
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        
        # 디버그 모드에서만 상세 정보 제공
        message = "Internal server error"
        details = None
        
        if settings.DEBUG:
            message = str(exc)
            details = traceback.format_exc()
        
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="INTERNAL_ERROR",
            message=message,
            details=details if settings.DEBUG else None
        )

def create_error_response(
    status_code: int,
    error_code: str,
    message: Union[str, Dict[str, Any]],
    details: Any = None,
    headers: Dict[str, str] = None
) -> JSONResponse:
    """
    표준화된 오류 응답 생성
    
    Args:
        status_code: HTTP 상태 코드
        error_code: 오류 코드
        message: 오류 메시지
        details: 추가 세부 정보
        headers: 응답 헤더
    
    Returns:
        JSONResponse: 표준화된 오류 응답
    """
    response = {
        "error": {
            "code": error_code,
            "message": message
        }
    }
    
    if details:
        response["error"]["details"] = details
    
    # 타임스탬프 추가
    response["error"]["timestamp"] = datetime.utcnow().isoformat()
    
    return JSONResponse(
        status_code=status_code,
        content=response,
        headers=headers
    )