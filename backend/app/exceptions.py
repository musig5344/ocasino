import logging
from typing import List
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError

# from backend.core.exceptions import AppException
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

def register_exception_handlers(app: FastAPI):
    """Register custom exception handlers for the FastAPI app."""

    # Remove or comment out the generic AppException handler if specific handlers cover its cases
    # @app.exception_handler(AppException)
    # async def app_exception_handler(request: Request, exc: AppException): ...

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
        
    @app.exception_handler(PydanticValidationError)
    async def pydantic_validation_exception_handler(request: Request, exc: PydanticValidationError):
        details: List[ErrorResponseDetail] = []
        for error in exc.errors():
             details.append(ErrorResponseDetail(
                 loc=[str(loc) for loc in error.get('loc', [])],
                 msg=error.get('msg', 'Validation error'),
                 type=error.get('type', 'value_error')
             ))
        logger.warning(f"Pydantic validation error occurred: {details}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
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
        logger.error(f"Business logic error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, 
            content=ErrorResponse(message=str(exc), error_code="business_rule_violation").model_dump(exclude_none=True)
        )
        
    @app.exception_handler(DatabaseError)
    async def database_exception_handler(request: Request, exc: DatabaseError):
        logger.error(f"Database error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(message="An unexpected database error occurred.", error_code="database_error").model_dump(exclude_none=True)
        )

    # Keep the general Exception handler as a catch-all
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled exception occurred: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(message="An unexpected internal server error occurred.", error_code="internal_server_error").model_dump(exclude_none=True)
        )

    logger.info("Standard exception handlers registered.") 