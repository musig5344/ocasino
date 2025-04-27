from pydantic import BaseModel, Field
from typing import Optional, Any, List, Generic, TypeVar

# Generic TypeVar for data payload
T = TypeVar('T')

class ErrorDetail(BaseModel):
    """에러 상세 정보"""
    code: str = Field(..., description="에러 코드 (예: INSUFFICIENT_FUNDS)")
    message: str = Field(..., description="에러 설명")

class ErrorResponse(BaseModel):
    """표준 에러 응답 스키마"""
    error: ErrorDetail
    
    class Config:
        schema_extra = {
            "examples": {
                 "insufficient_funds": {
                     "summary": "잔액 부족 에러",
                     "value": {
                         "error": {
                             "code": "INSUFFICIENT_FUNDS",
                             "message": "플레이어의 잔액이 부족합니다."
                         }
                     }
                 },
                 "validation_error": {
                     "summary": "입력값 검증 에러",
                     "value": {
                         "error": {
                             "code": "VALIDATION_ERROR",
                             "message": "입력값이 유효하지 않습니다: [필드명] - [오류 상세]" 
                         }
                     }
                 },
                  "not_found": {
                     "summary": "리소스를 찾을 수 없음",
                     "value": {
                         "error": {
                             "code": "RESOURCE_NOT_FOUND",
                             "message": "요청한 리소스를 찾을 수 없습니다." 
                         }
                     }
                 },
                 "internal_server_error": {
                     "summary": "내부 서버 오류",
                     "value": {
                         "error": {
                             "code": "INTERNAL_SERVER_ERROR",
                             "message": "요청 처리 중 서버 내부 오류가 발생했습니다."
                         }
                     }
                 },
                 "permission_denied": {
                      "summary": "권한 없음",
                      "value": {
                          "error": {
                              "code": "PERMISSION_DENIED",
                              "message": "요청한 작업을 수행할 권한이 없습니다."
                          }
                      }
                 },
                 "service_unavailable": {
                      "summary": "서비스 이용 불가",
                      "value": {
                           "error": {
                               "code": "SERVICE_UNAVAILABLE",
                               "message": "현재 서비스를 이용할 수 없습니다. 잠시 후 다시 시도해주세요."
                           }
                      }
                 }
            }
        } 

class StandardResponse(BaseModel, Generic[T]):
    """모든 API 응답의 기본 형식"""
    success: bool = True
    message: Optional[str] = None
    data: Optional[T] = None # Use Generic TypeVar for data

class ErrorResponseDetail(BaseModel):
    """Specific error detail structure (optional)"""
    loc: Optional[List[str]] = None # Field location for validation errors
    msg: str
    type: str

class ErrorResponse(BaseModel):
    """Standard Error Response structure"""
    success: bool = False
    message: str
    error_code: Optional[str] = None # Custom error code (e.g., 'resource_not_found')
    details: Optional[List[ErrorResponseDetail]] = None # For validation errors

class PaginatedData(BaseModel, Generic[T]):
    """Data structure for paginated responses"""
    items: List[T]
    page: int
    page_size: int
    total_items: int
    total_pages: int

class PaginatedResponse(StandardResponse[PaginatedData[T]]):
    """페이지네이션 정보를 포함한 표준 응답 형식"""
    # Inherits success, message from StandardResponse
    # The 'data' field will hold the PaginatedData structure
    pass

# Example Usage (in API endpoint):
# return StandardResponse[PartnerSchema](data=partner_data, message="Partner retrieved successfully.")
# return PaginatedResponse[PartnerSchema](data=paginated_partner_data, message="Partners listed.")
# return ErrorResponse(message="Partner not found", error_code="partner_not_found") 