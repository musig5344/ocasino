from fastapi import APIRouter, Depends, Query, Path, status, Response, BackgroundTasks, HTTPException, Body
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any, Tuple, Union, Annotated
import logging
from datetime import date, datetime, timedelta
from uuid import UUID

# Assuming dependencies remain accessible or will be moved
# from backend.api.dependencies.db import get_db # 이전 경로 주석 처리
# from backend.api.dependencies.auth import (
#     get_current_partner_id, require_permission, get_current_permissions
# ) # 이전 경로 주석 처리
# from backend.api.dependencies.common import (
#     common_pagination_params, parse_date_range
# ) # 이전 경로 주석 처리

from backend.core.dependencies import (
    get_db,
    get_current_partner_id,
    require_permission, # 사용하지 않더라도 공통 의존성이므로 이동
    get_current_permissions,
    common_pagination_params,
    # parse_date_range # Remove this import
) # 새로운 공통 의존성 사용

# --- Temporarily comment out report schema imports and usage ---
# from backend.schemas.report import (
#     ReportCreate, ReportResponse, ReportList,
#     SettlementResponse, SettlementList,
#     ReportTypeResponse, ReportTypeList,
#     ReportExportFormat
# )
from backend.services.reporting.reporting_service import ReportingService
# SettlementService가 구현되면 주석 해제
# from backend.services.reporting.settlement_service import SettlementService
from backend.core.exceptions import (
    # ResourceNotFoundException, # Use NotFoundError instead
    NotFoundError, # Correct exception name
    AuthorizationError, # Correct exception name
    InvalidInputError, # Correct exception name
    ServiceUnavailableException,
    PermissionDeniedError
)
from backend.core.schemas import StandardResponse, PaginatedResponse, ErrorResponseDetail, ErrorResponse

# Standard Response Utils
from backend.utils.response import success_response, paginated_response

router = APIRouter() # Prefix will be handled in api.py
logger = logging.getLogger(__name__)

# 유틸리티 함수
# def create_report_response(report: Any, report_type: Any = None) -> ReportResponse:
    # ... (Keep function commented out for now)

@router.get(
    "/types",
    # response_model=PaginatedResponse[ReportTypeResponse],
    tags=["Reports"],
    summary="사용 가능한 보고서 유형 목록 조회",
    description='''
    현재 파트너가 생성 요청할 수 있는 보고서 유형의 목록을 반환합니다.
    각 유형은 고유 ID, 코드, 이름, 설명 및 생성 시 필요한 파라미터 정보(`parameters`)와 지원하는 파일 형식(`available_formats`)을 포함할 수 있습니다.

    **권한 요구사항:** `reports.types.read`
    ''',
    responses={
        status.HTTP_200_OK: {"description": "보고서 유형 목록 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근", "content": {"application/json": {"example": {"error": {"code": "AUTH_401_UNAUTHORIZED", "message": "Authentication required"}}}}},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "보고서 유형 조회 권한 없음 (`reports.types.read` 필요)", "content": {"application/json": {"example": {"error": {"code": "AUTH_403_FORBIDDEN", "message": "Permission denied: reports.types.read required"}}}}},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "서버 내부 오류 발생", "content": {"application/json": {"example": {"error": {"code": "SYS_500_INTERNAL_ERROR", "message": "An unexpected error occurred"}}}}}
    }
)
async def list_report_types(
    db: AsyncSession = Depends(get_db),
    partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    '''
    사용 가능한 보고서 유형 목록을 조회합니다.
    파트너별 접근 가능한 보고서 유형이 다를 수 있습니다.

    **권한 요구사항:** `reports.types.read`
    '''
    if "reports.types.read" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to list report types")
        
    report_service = ReportingService(db)
    report_types = await report_service.list_allowed_report_types(partner_id)
    
    # return paginated_response(items=report_types, total=len(report_types), page=1, page_size=len(report_types))
    return success_response(data=report_types, message="Report types retrieved (schema pending).") # Temporary response

@router.post(
    "",
    # response_model=StandardResponse[ReportResponse],
    tags=["Reports"],
    summary="새 보고서 생성 요청 (비동기)",
    description='''
    지정된 유형(`report_type_id`)과 파라미터(`parameters`)로 새로운 보고서 생성을 **비동기적으로 요청**합니다.

    - **요청 성공 시 (202 Accepted):** 즉시 보고서 메타데이터(ID, 초기 상태 'pending' 등)를 반환합니다. 실제 보고서 파일 생성은 백그라운드에서 수행됩니다.
    - **생성 진행 상태:** 생성된 보고서의 상태(`status`)는 보고서 목록 조회(`GET /reports`) 또는 상세 조회(`GET /reports/{report_id}`) API를 통해 주기적으로 확인해야 합니다 (pending -> processing -> completed / failed).
    - **파라미터 유효성:** 요청된 보고서 유형에 필요한 파라미터가 누락되거나 형식이 잘못된 경우 `422 Unprocessable Entity` 오류가 발생합니다.
    - **권한:** 파트너는 자신에게 허용된 보고서 유형(`report_type_id`)만 생성할 수 있습니다.

    **권한 요구사항:** `reports.generate`
    ''',
    response_description="보고서 생성 요청이 성공적으로 접수되었으며, 백그라운드 생성이 시작됨을 나타내는 보고서 메타데이터입니다.",
    responses={
        status.HTTP_202_ACCEPTED: {"description": "보고서 생성 요청 접수 성공 (백그라운드 처리 시작)"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근", "content": {"application/json": {"example": {"error": {"code": "AUTH_401_UNAUTHORIZED", "message": "Authentication required"}}}}},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 보고서 유형 생성 권한 없음 (`reports.generate` 필요)", "content": {"application/json": {"example": {"error": {"code": "AUTH_403_FORBIDDEN", "message": "Permission denied: reports.generate required or report type not allowed"}}}}},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "요청한 보고서 유형 (`report_type_id`)을 찾을 수 없음", "content": {"application/json": {"example": {"error": {"code": "REPORT_404_TYPE_NOT_FOUND", "message": "Report type with ID a1b2c3d4... not found"}}}}},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "요청 본문 유효성 검증 실패 (필수 필드 누락, 잘못된 포맷, 유효하지 않은 파라미터 값 등)", "content": {"application/json": {"example": {"error": {"code": "REPORT_422_INVALID_PARAMS", "message": "Invalid parameter value for 'month': '2024-13'"}}}}},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "보고서 생성 요청 처리 중 서버 내부 오류 발생", "content": {"application/json": {"example": {"error": {"code": "SYS_500_INTERNAL_ERROR", "message": "Failed to initiate report generation"}}}}}
    }
)
async def request_report_generation(
    # Use Annotated for clarity and correct order
    report_data: Annotated[Dict[str, Any], Body(...)], # Keep as Dict for now
    background_tasks: BackgroundTasks, # Special FastAPI dependency
    db: Annotated[AsyncSession, Depends(get_db)],
    partner_id: Annotated[UUID, Depends(get_current_partner_id)],
    requesting_permissions: Annotated[List[str], Depends(get_current_permissions)]
):
    '''
    새 보고서 생성을 비동기적으로 요청합니다.

    # - **report_data**: 생성할 보고서 정보 (유형 ID, 포맷, 이름, 파라미터).
    - **report_data**: 생성할 보고서 정보 (Dict 형태).

    **권한 요구사항:** `reports.generate`
    '''
    if "reports.generate" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to generate reports")
        
    report_service = ReportingService(db)
    
    # report_data is already a dict here
    report = await report_service.request_report_generation(
        partner_id=partner_id,
        report_data=report_data # Pass dict directly
    )
    
    background_tasks.add_task(
        report_service.generate_report_in_background,
        report_id=report.id
    )
    
    logger.info(f"Report generation requested: {report.id} by partner {partner_id}")
    
    # report_type = await report_service.get_report_type(report.report_type_id)
    response_data = {"report_id": str(report.id), "status": report.status} # Temporary response data
    response_content = success_response(data=response_data, message="Report generation requested successfully.").model_dump()
    return JSONResponse(content=response_content, status_code=status.HTTP_202_ACCEPTED)

@router.get(
    "",
    # response_model=PaginatedResponse[ReportResponse],
    tags=["Reports"],
    summary="생성된 보고서 목록 조회 (페이지네이션)",
    description='''
    현재 파트너가 생성 요청했거나 접근 권한이 있는 보고서들의 목록을 조회합니다.
    다양한 필터(보고서 유형 ID, 상태, 생성일자 범위)와 페이지네이션을 지원합니다.

    - **report_type_id:** 특정 보고서 유형으로 필터링합니다.
    - **status:** 보고서 상태(`pending`, `processing`, `completed`, `failed`)로 필터링합니다.
    - **start_date / end_date:** 보고서 생성 요청일(`created_at`) 기준으로 기간 필터링합니다.
    - **page / page_size:** 결과를 페이지 단위로 나누어 조회합니다.

    **권한 요구사항:** `reports.read`
    ''',
    responses={
        status.HTTP_200_OK: {"description": "보고서 목록 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근", "content": {"application/json": {"example": {"error": {"code": "AUTH_401_UNAUTHORIZED", "message": "Authentication required"}}}}},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "보고서 목록 조회 권한 없음 (`reports.read` 필요)", "content": {"application/json": {"example": {"error": {"code": "AUTH_403_FORBIDDEN", "message": "Permission denied: reports.read required"}}}}},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "잘못된 필터 파라미터 형식 또는 값 (예: 날짜 형식 오류, 잘못된 상태 값)", "content": {"application/json": {"example": {"error": {"code": "REPORT_422_INVALID_FILTER", "message": "Invalid date format for 'start_date'"}}}}},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "보고서 목록 조회 중 서버 내부 오류 발생", "content": {"application/json": {"example": {"error": {"code": "SYS_500_INTERNAL_ERROR", "message": "Failed to retrieve reports"}}}}}
    }
)
async def list_reports(
    report_type_id: Optional[UUID] = Query(None, description="필터링할 보고서 유형의 고유 ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="필터링할 보고서 상태 (pending, processing, completed, failed)", example="completed", pattern="^(pending|processing|completed|failed)$"),
    # date_range: Tuple[Optional[datetime], Optional[datetime]] = Depends(parse_date_range), # Remove dependency
    # Add start_date and end_date query parameters
    start_date: Optional[datetime] = Query(None, description="Filter start date (ISO format, created_at)"),
    end_date: Optional[datetime] = Query(None, description="Filter end date (ISO format, created_at)"),
    pagination: Dict[str, Any] = Depends(common_pagination_params),
    db: AsyncSession = Depends(get_db),
    partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    '''
    생성된 보고서 목록을 조회합니다.

    - **report_type_id**: 보고서 유형 ID 필터.
    - **status_filter**: 보고서 상태 필터.
    # - **date_range**: 생성일 기준 날짜 범위 필터.
    - **start_date**: 생성일 기준 시작 날짜 필터.
    - **end_date**: 생성일 기준 종료 날짜 필터.
    - **pagination**: 페이지네이션 파라미터.

    **권한 요구사항:** `reports.read`
    '''
    if "reports.read" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to list reports")
        
    report_service = ReportingService(db)
    # start_date, end_date = date_range # Remove assignment
    
    reports, total = await report_service.list_reports(
        partner_id=partner_id,
        skip=pagination["offset"],
        limit=pagination["limit"],
        report_type_id=report_type_id,
        status=status_filter,
        start_date=start_date, # Use parameter directly
        end_date=end_date # Use parameter directly
    )
    
    # report_responses = []
    # for report in reports:
    #     report_type = await report_service.get_report_type(report.report_type_id)
    #     report_responses.append(create_report_response(report, report_type))
    # return paginated_response(
    #     items=report_responses,
    #     total=total,
    #     page=pagination.get("page", 1),
    #     page_size=pagination["limit"]
    # )
    return paginated_response(items=reports, total=total, page=pagination.get("page", 1), page_size=pagination["limit"]) # Temporary response

@router.get(
    "/{report_id}",
    # response_model=StandardResponse[ReportResponse],
    tags=["Reports"],
    summary="특정 보고서 상세 정보 조회",
    description='''
    지정된 보고서 ID(`report_id`)에 해당하는 보고서의 상세 정보를 조회합니다.
    보고서의 현재 상태(`status`), 생성 파라미터(`parameters`), 완료 시간(`completed_at`), 파일 크기(`file_size`, 완료 시), 오류 메시지(`error_message`, 실패 시) 등을 포함합니다.
    파트너는 자신이 요청한 보고서만 조회할 수 있습니다.

    **권한 요구사항:** `reports.read`
    ''',
    responses={
        status.HTTP_200_OK: {"description": "보고서 상세 정보 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근", "content": {"application/json": {"example": {"error": {"code": "AUTH_401_UNAUTHORIZED", "message": "Authentication required"}}}}},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 보고서 조회 권한 없음 (`reports.read` 필요 또는 다른 파트너의 보고서)", "content": {"application/json": {"example": {"error": {"code": "AUTH_403_FORBIDDEN", "message": "Permission denied to access report b2c3..."}}}}},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정한 ID의 보고서를 찾을 수 없음", "content": {"application/json": {"example": {"error": {"code": "REPORT_404_NOT_FOUND", "message": "Report with ID b2c3... not found"}}}}},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "보고서 정보 조회 중 서버 내부 오류 발생", "content": {"application/json": {"example": {"error": {"code": "SYS_500_INTERNAL_ERROR", "message": "Failed to retrieve report details"}}}}}
    }
)
async def get_report(
    report_id: UUID = Path(..., description="상세 정보를 조회할 보고서의 고유 ID"),
    db: AsyncSession = Depends(get_db),
    partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    '''
    특정 보고서의 상세 정보를 조회합니다.

    - **report_id**: 조회할 보고서의 UUID.

    **권한 요구사항:** `reports.read`
    '''
    if "reports.read" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to view this report")
        
    report_service = ReportingService(db)
    
    report = await report_service.get_report(report_id, partner_id)
    # report_type = await report_service.get_report_type(report.report_type_id)
    # response_data = create_report_response(report, report_type)
    response_data = report # Temporary response data
    return success_response(data=response_data)

@router.get(
    "/{report_id}/download",
    tags=["Reports"],
    summary="보고서 파일 다운로드",
    description='''
    생성이 완료된 (`status`가 `completed`인) 특정 보고서 파일을 다운로드합니다.

    - **성공 시:** 보고서 파일(`content-type`은 보고서 포맷에 따라 다름, 예: `text/csv`, `application/json`)을 스트리밍으로 반환합니다. `Content-Disposition` 헤더에 파일명이 포함됩니다.
    - **실패 조건:**
        - 보고서가 아직 생성 중(`pending`, `processing`)이거나 실패(`failed`)한 경우 `422 Unprocessable Entity` 오류가 발생합니다.
        - 보고서 파일 자체를 찾을 수 없는 경우(드문 경우) `404 Not Found` 오류가 발생합니다.

    파트너는 자신이 요청한 보고서만 다운로드할 수 있습니다.

    **권한 요구사항:** `reports.download`
    ''',
    response_description="보고서 파일 스트림. Content-Type과 Content-Disposition 헤더가 설정됩니다.",
    responses={
        status.HTTP_200_OK: {"description": "보고서 파일 다운로드 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근", "content": {"application/json": {"example": {"error": {"code": "AUTH_401_UNAUTHORIZED", "message": "Authentication required"}}}}},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 보고서 다운로드 권한 없음 (`reports.download` 필요 또는 다른 파트너 보고서)", "content": {"application/json": {"example": {"error": {"code": "AUTH_403_FORBIDDEN", "message": "Permission denied to download report b2c3..."}}}}},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정한 ID의 보고서 또는 생성된 파일을 찾을 수 없음", "content": {"application/json": {"example": {"error": {"code": "REPORT_404_FILE_NOT_FOUND", "message": "Report file for ID b2c3... not found or report does not exist"}}}}},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "보고서가 다운로드 가능한 상태가 아님 (예: 아직 생성 중 또는 실패)", "content": {"application/json": {"example": {"error": {"code": "REPORT_422_NOT_COMPLETED", "message": "Report b2c3... is not in 'completed' status"}}}}},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "파일 다운로드 처리 중 서버 내부 오류 발생", "content": {"application/json": {"example": {"error": {"code": "SYS_500_INTERNAL_ERROR", "message": "Failed to process report download"}}}}}
    }
)
async def download_report(
    report_id: UUID = Path(..., description="다운로드할 보고서의 고유 ID"),
    db: AsyncSession = Depends(get_db),
    partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    '''
    생성이 완료된 보고서 파일을 다운로드합니다.

    - **report_id**: 다운로드할 보고서의 UUID.

    **권한 요구사항:** `reports.download`
    '''
    if "reports.download" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to download this report")

    report_service = ReportingService(db)
    
    file_stream_response = await report_service.download_report_file(
        report_id=report_id,
        partner_id=partner_id
    )
    
    return file_stream_response

@router.get(
    "/settlements",
    # response_model=PaginatedResponse[SettlementResponse],
    tags=["Settlements"],
    summary="정산 내역 목록 조회 (페이지네이션)",
    description='''
    현재 파트너의 정산 내역 목록을 조회합니다.
    기간(`start_date`, `end_date`) 및 정산 상태(`status`)별 필터링과 페이지네이션을 지원합니다.

    **참고:** 정산 기능이 활성화되지 않았거나 관련 서비스(`SettlementService`)가 구현되지 않은 경우 503 오류가 발생할 수 있습니다.

    **권한 요구사항:** `settlements.read`
    ''',
    responses={
        status.HTTP_200_OK: {"description": "정산 내역 목록 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근", "content": {"application/json": {"example": {"error": {"code": "AUTH_401_UNAUTHORIZED", "message": "Authentication required"}}}}},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "정산 내역 조회 권한 없음 (`settlements.read` 필요)", "content": {"application/json": {"example": {"error": {"code": "AUTH_403_FORBIDDEN", "message": "Permission denied: settlements.read required"}}}}},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "잘못된 필터 파라미터 형식 또는 값", "content": {"application/json": {"example": {"error": {"code": "SETTLE_422_INVALID_FILTER", "message": "Invalid status filter value"}}}}},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "정산 내역 조회 중 서버 내부 오류 발생", "content": {"application/json": {"example": {"error": {"code": "SYS_500_INTERNAL_ERROR", "message": "Failed to retrieve settlements"}}}}},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse, "description": "정산 서비스를 현재 사용할 수 없음 (미구현 또는 일시적 오류)", "content": {"application/json": {"example": {"error": {"code": "SYS_503_SERVICE_UNAVAILABLE", "message": "Settlement service is currently unavailable"}}}}}
    }
)
async def list_settlements(
    status_filter: Optional[str] = Query(None, alias="status", description="필터링할 정산 상태 (예: pending, processing, completed, failed)", example="completed"),
    # date_range: Tuple[Optional[datetime], Optional[datetime]] = Depends(parse_date_range), # Remove dependency
    # Add start_date and end_date query parameters
    start_date: Optional[datetime] = Query(None, description="Filter start date (ISO format, period_start/end)"),
    end_date: Optional[datetime] = Query(None, description="Filter end date (ISO format, period_start/end)"),
    pagination: Dict[str, Any] = Depends(common_pagination_params),
    db: AsyncSession = Depends(get_db),
    partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    '''
    정산 내역 목록을 조회합니다.

    # - **date_range**: 정산 기간 필터.
    - **start_date**: 정산 기간 시작 날짜 필터.
    - **end_date**: 정산 기간 종료 날짜 필터.
    - **status_filter**: 정산 상태 필터.
    - **pagination**: 페이지네이션 파라미터.

    **권한 요구사항:** `settlements.read`
    '''
    if "settlements.read" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to list settlements")

    report_service = ReportingService(db)
    settlements, total = await report_service.list_settlements(
        partner_id=partner_id,
        skip=pagination["offset"],
        limit=pagination["limit"],
        status=status_filter,
        start_date=start_date, # Use parameter directly
        end_date=end_date # Use parameter directly
    )
    
    return paginated_response(items=settlements, total=total, page=pagination.get("page", 1), page_size=pagination["limit"]) # Temporary response

@router.get(
    "/settlements/{settlement_id}",
    # response_model=StandardResponse[SettlementResponse],
    tags=["Settlements"],
    summary="특정 정산 내역 상세 조회",
    description='''
    지정된 정산 ID(`settlement_id`)에 해당하는 정산 내역의 상세 정보를 조회합니다.
    정산 기간, 금액, 통화, 상태, 처리 일시 등을 포함합니다.
    파트너는 자신의 정산 내역만 조회할 수 있습니다.

    **참고:** 정산 기능이 활성화되지 않았거나 관련 서비스(`SettlementService`)가 구현되지 않은 경우 503 오류가 발생할 수 있습니다.

    **권한 요구사항:** `settlements.read`
    ''',
    responses={
        status.HTTP_200_OK: {"description": "정산 상세 정보 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근", "content": {"application/json": {"example": {"error": {"code": "AUTH_401_UNAUTHORIZED", "message": "Authentication required"}}}}},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 정산 내역 조회 권한 없음 (`settlements.read` 필요 또는 다른 파트너 정산)", "content": {"application/json": {"example": {"error": {"code": "AUTH_403_FORBIDDEN", "message": "Permission denied to access settlement d4e5..."}}}}},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정한 ID의 정산 내역을 찾을 수 없음", "content": {"application/json": {"example": {"error": {"code": "SETTLE_404_NOT_FOUND", "message": "Settlement with ID d4e5... not found"}}}}},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "정산 정보 조회 중 서버 내부 오류 발생", "content": {"application/json": {"example": {"error": {"code": "SYS_500_INTERNAL_ERROR", "message": "Failed to retrieve settlement details"}}}}},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse, "description": "정산 서비스를 현재 사용할 수 없음 (미구현 또는 일시적 오류)", "content": {"application/json": {"example": {"error": {"code": "SYS_503_SERVICE_UNAVAILABLE", "message": "Settlement service is currently unavailable"}}}}}
    }
)
async def get_settlement(
    settlement_id: UUID = Path(..., description="상세 정보를 조회할 정산 내역의 고유 ID"),
    db: AsyncSession = Depends(get_db),
    partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    '''
    특정 정산 내역의 상세 정보를 조회합니다.

    - **settlement_id**: 조회할 정산의 UUID.

    **권한 요구사항:** `settlements.read`
    '''
    if "settlements.read" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to view this settlement")

    report_service = ReportingService(db)
    
    settlement = await report_service.get_settlement(settlement_id, partner_id)
    return success_response(data=settlement) # Temporary response 