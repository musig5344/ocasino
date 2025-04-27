from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from typing import Union, Dict, Any, List, Optional
import logging
import traceback
from datetime import datetime

from backend.api.errors.exceptions import BaseAPIException
from backend.core.config import settings
from backend.core.exceptions import (
    NotFoundError, 
    ValidationError as ServiceValidationError,
    ConflictError, 
    AuthenticationError, 
    PermissionDeniedError, 
    BusinessLogicError,
    DatabaseError
)
from backend.core.schemas import ErrorResponse, ErrorResponseDetail

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

def add_exception_handlers(app: FastAPI):
    """FastAPI 애플리케이션에 표준 예외 핸들러를 추가합니다."""
    
    @app.exception_handler(NotFoundError)
    async def not_found_exception_handler(request: Request, exc: NotFoundError):
        logger.info(f"Resource not found: {exc}")
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorResponse(message=str(exc), error_code="resource_not_found").model_dump(exclude_none=True)
        )

    @app.exception_handler(ServiceValidationError)
    async def service_validation_exception_handler(request: Request, exc: ServiceValidationError):
        logger.info(f"Service validation error: {exc}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ErrorResponse(message=str(exc), error_code="validation_error").model_dump(exclude_none=True)
        )

    @app.exception_handler(RequestValidationError)
    async def fast_api_validation_exception_handler(request: Request, exc: RequestValidationError):
        """Handles FastAPI's built-in request validation errors."""
        details: List[ErrorResponseDetail] = []
        for error in exc.errors():
            details.append(ErrorResponseDetail(
                loc=[str(loc) for loc in error.get('loc', [])],
                msg=error.get('msg', 'Validation error'),
                type=error.get('type', 'value_error')
            ))
        logger.info(f"Request validation failed: {details}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                message="Request validation failed", 
                error_code="request_validation_error",
                details=details
            ).model_dump(exclude_none=True)
        )
        
    @app.exception_handler(PydanticValidationError) # Catch Pydantic errors if they leak
    async def pydantic_validation_exception_handler(request: Request, exc: PydanticValidationError):
        """Handles Pydantic validation errors that might occur outside FastAPI's scope."""
        details: List[ErrorResponseDetail] = []
        for error in exc.errors():
             details.append(ErrorResponseDetail(
                 loc=[str(loc) for loc in error.get('loc', [])],
                 msg=error.get('msg', 'Validation error'),
                 type=error.get('type', 'value_error')
             ))
        logger.warning(f"Pydantic validation error occurred: {details}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, # Or 422
            content=ErrorResponse(
                message="Data validation error", 
                error_code="pydantic_validation_error",
                details=details
            ).model_dump(exclude_none=True)
        )

    @app.exception_handler(ConflictError)
    async def conflict_exception_handler(request: Request, exc: ConflictError):
        logger.info(f"Conflict error: {exc}")
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=ErrorResponse(message=str(exc), error_code="conflict").model_dump(exclude_none=True)
        )

    @app.exception_handler(AuthenticationError)
    async def authentication_exception_handler(request: Request, exc: AuthenticationError):
        logger.warning(f"Authentication error: {exc}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=ErrorResponse(message=str(exc), error_code="authentication_failed").model_dump(exclude_none=True)
        )

    @app.exception_handler(PermissionDeniedError)
    async def permission_exception_handler(request: Request, exc: PermissionDeniedError):
        logger.warning(f"Permission denied: {exc}")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=ErrorResponse(message=str(exc), error_code="permission_denied").model_dump(exclude_none=True)
        )
        
    @app.exception_handler(BusinessLogicError)
    async def business_logic_exception_handler(request: Request, exc: BusinessLogicError):
        logger.error(f"Business logic error: {exc}", exc_info=True) # Log with traceback for business errors
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, # Often a bad request due to business rules
            content=ErrorResponse(message=str(exc), error_code="business_rule_violation").model_dump(exclude_none=True)
        )
        
    @app.exception_handler(DatabaseError)
    async def database_exception_handler(request: Request, exc: DatabaseError):
        logger.error(f"Database error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(message="An unexpected database error occurred.", error_code="database_error").model_dump(exclude_none=True)
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        # Catch-all for any other unexpected errors
        logger.exception(f"Unhandled exception occurred: {exc}") # Log full traceback
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(message="An unexpected internal server error occurred.", error_code="internal_server_error").model_dump(exclude_none=True)
        )

    logger.info("Standard exception handlers added to the application.")