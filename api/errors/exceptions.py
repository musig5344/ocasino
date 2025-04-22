from fastapi import HTTPException, status
from typing import Optional, Any, Dict

class BaseAPIException(HTTPException):
    """
    기본 API 예외 클래스
    """
    def __init__(
        self,
        status_code: int,
        detail: Any = None,
        headers: Optional[Dict[str, Any]] = None,
        error_code: str = "INTERNAL_ERROR"
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.error_code = error_code

class ResourceNotFoundException(BaseAPIException):
    """
    리소스 없음 예외
    """
    def __init__(self, resource: str, resource_id: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} with ID {resource_id} not found",
            error_code="RESOURCE_NOT_FOUND"
        )

class DuplicateResourceException(BaseAPIException):
    """
    중복 리소스 예외
    """
    def __init__(self, resource: str, identifier: str = None):
        detail = f"Duplicate {resource}"
        if identifier:
            detail += f" with identifier {identifier}"
        
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
            error_code="DUPLICATE_RESOURCE"
        )

class InvalidRequestException(BaseAPIException):
    """
    잘못된 요청 예외
    """
    def __init__(self, detail: str = "Invalid request"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code="INVALID_REQUEST"
        )

class UnauthorizedException(BaseAPIException):
    """
    인증 실패 예외
    """
    def __init__(self, detail: str = "Authentication required"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="UNAUTHORIZED",
            headers={"WWW-Authenticate": "Bearer"}
        )

class ForbiddenException(BaseAPIException):
    """
    권한 없음 예외
    """
    def __init__(self, detail: str = "Permission denied"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="FORBIDDEN"
        )

class InsufficientFundsException(BaseAPIException):
    """
    잔액 부족 예외
    """
    def __init__(self, detail: str = "Insufficient funds"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code="INSUFFICIENT_FUNDS"
        )

class ServiceUnavailableException(BaseAPIException):
    """
    서비스 이용 불가 예외
    """
    def __init__(self, detail: str = "Service temporarily unavailable"):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
            error_code="SERVICE_UNAVAILABLE"
        )

class ValidationException(BaseAPIException):
    """
    유효성 검증 실패 예외
    """
    def __init__(self, detail: str = "Validation failed", errors: Optional[Dict[str, Any]] = None):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
            error_code="VALIDATION_ERROR"
        )
        self.errors = errors

class RateLimitExceededException(BaseAPIException):
    """
    속도 제한 초과 예외
    """
    def __init__(self, detail: str = "Rate limit exceeded"):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            error_code="RATE_LIMIT_EXCEEDED"
        )