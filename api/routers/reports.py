from fastapi import APIRouter, Depends, Query, Path, status, Response, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, List
import logging
from datetime import date, datetime, timedelta

from backend.api.dependencies.db import get_db
from backend.api.dependencies.auth import get_current_partner_id, verify_permissions
from backend.api.dependencies.common import common_pagination_params, parse_date_range
from backend.models.schemas.report import (
    ReportCreate, ReportResponse, ReportList,
    SettlementResponse, SettlementList,
    ReportTypeResponse, ReportTypeList,
    ReportExportFormat
)
from backend.services.reporting.report_service import ReportService
from backend.services.reporting.settlement_service import SettlementService
from backend.api.errors.exceptions import (
    ResourceNotFoundException, ForbiddenException, InvalidRequestException,
    ServiceUnavailableException
)

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/types", response_model=ReportTypeList)
async def list_report_types(
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id)
):
    """
    사용 가능한 보고서 유형 목록 조회
    
    파트너는 자신에게 허용된 보고서 유형만 볼 수 있습니다.
    """
    report_service = ReportService(db)
    
    # 보고서 유형 목록 조회
    report_types = await report_service.list_report_types(partner_id)
    
    # 응답 생성
    items = []
    for report_type in report_types:
        items.append(ReportTypeResponse(
            id=report_type.id,
            code=report_type.code,
            name=report_type.name,
            description=report_type.description,
            available_formats=report_type.available_formats,
            parameters=report_type.parameters
        ))
    
    return ReportTypeList(
        items=items,
        count=len(items)
    )

@router.post("", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def generate_report(
    report_data: ReportCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id)
):
    """
    새 보고서 생성 요청
    
    파트너는 자신에게 허용된 보고서 유형만 생성할 수 있습니다.
    보고서는 비동기적으로 생성되며, 완료되면 조회할 수 있습니다.
    """
    # 보고서 생성 권한 확인
    await verify_permissions("reports.generate")
    
    report_service = ReportService(db)
    
    # 보고서 유형 확인
    report_type = await report_service.get_report_type(report_data.report_type_id)
    if not report_type:
        raise ResourceNotFoundException("Report Type", report_data.report_type_id)
    
    # 파트너에게 허용된 보고서 유형인지 확인
    if not await report_service.is_report_type_allowed(partner_id, report_data.report_type_id):
        raise ForbiddenException(f"Report type {report_type.code} is not allowed for your partner")
    
    # 포맷 확인
    if report_data.format not in report_type.available_formats:
        raise InvalidRequestException(f"Format {report_data.format} is not available for report type {report_type.code}")
    
    # 파라미터 검증
    try:
        await report_service.validate_report_parameters(report_type.id, report_data.parameters)
    except ValueError as e:
        raise InvalidRequestException(str(e))
    
    # 보고서 생성 요청
    report = await report_service.create_report_request(
        partner_id=partner_id,
        report_type_id=report_data.report_type_id,
        format=report_data.format,
        parameters=report_data.parameters,
        name=report_data.name
    )
    
    # 백그라운드에서 보고서 생성
    background_tasks.add_task(
        report_service.generate_report_in_background,
        report_id=report.id
    )
    
    logger.info(f"Report generation requested: {report.id} ({report_type.code}) by partner {partner_id}")
    
    return ReportResponse(
        id=report.id,
        partner_id=report.partner_id,
        report_type=ReportTypeResponse(
            id=report_type.id,
            code=report_type.code,
            name=report_type.name,
            description=report_type.description
        ),
        name=report.name,
        status=report.status,
        format=report.format,
        parameters=report.parameters,
        created_at=report.created_at,
        completed_at=report.completed_at
    )

@router.get("", response_model=ReportList)
async def list_reports(
    report_type_id: Optional[str] = Query(None, description="보고서 유형 ID로 필터링"),
    status: Optional[str] = Query(None, description="상태로 필터링 (pending, processing, completed, failed)"),
    date_range: dict = Depends(parse_date_range),
    pagination: dict = Depends(common_pagination_params),
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id)
):
    """
    보고서 목록 조회
    
    파트너는 자신이 요청한 보고서만 볼 수 있습니다.
    """
    # 보고서 조회 권한 확인
    await verify_permissions("reports.read")
    
    report_service = ReportService(db)
    
    # 보고서 목록 조회
    reports, total = await report_service.list_reports(
        partner_id=partner_id,
        report_type_id=report_type_id,
        status=status,
        start_date=date_range["start_date"],
        end_date=date_range["end_date"],
        skip=pagination["skip"],
        limit=pagination["limit"]
    )
    
    # 보고서 유형 정보 가져오기
    report_type_ids = {report.report_type_id for report in reports}
    report_types = {
        rt.id: rt for rt in await report_service.get_report_types_by_ids(list(report_type_ids))
    }
    
    # 응답 생성
    items = []
    for report in reports:
        report_type = report_types.get(report.report_type_id)
        items.append(ReportResponse(
            id=report.id,
            partner_id=report.partner_id,
            report_type=ReportTypeResponse(
                id=report_type.id,
                code=report_type.code,
                name=report_type.name,
                description=report_type.description
            ) if report_type else None,
            name=report.name,
            status=report.status,
            format=report.format,
            parameters=report.parameters,
            created_at=report.created_at,
            completed_at=report.completed_at,
            file_size=report.file_size,
            error_message=report.error_message if report.status == 'failed' else None
        ))
    
    return ReportList(
        items=items,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"]
    )

@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: str = Path(..., description="보고서 ID"),
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id)
):
    """
    보고서 세부 정보 조회
    
    파트너는 자신이 요청한 보고서만 볼 수 있습니다.
    """
    # 보고서 조회 권한 확인
    await verify_permissions("reports.read")
    
    report_service = ReportService(db)
    
    # 보고서 조회
    report = await report_service.get_report(report_id)
    if not report:
        raise ResourceNotFoundException("Report", report_id)
    
    # 권한 확인
    if report.partner_id != partner_id:
        try:
            await verify_permissions("reports.admin")
        except:
            raise ForbiddenException("You can only view your own reports")
    
    # 보고서 유형 정보 가져오기
    report_type = await report_service.get_report_type(report.report_type_id)
    
    return ReportResponse(
        id=report.id,
        partner_id=report.partner_id,
        report_type=ReportTypeResponse(
            id=report_type.id,
            code=report_type.code,
            name=report_type.name,
            description=report_type.description
        ) if report_type else None,
        name=report.name,
        status=report.status,
        format=report.format,
        parameters=report.parameters,
        created_at=report.created_at,
        completed_at=report.completed_at,
        file_size=report.file_size,
        error_message=report.error_message if report.status == 'failed' else None
    )

@router.get("/{report_id}/download")
async def download_report(
    report_id: str = Path(..., description="보고서 ID"),
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id)
):
    """
    보고서 파일 다운로드
    
    파트너는 자신이 요청한 보고서만 다운로드할 수 있습니다.
    """
    # 보고서 다운로드 권한 확인
    await verify_permissions("reports.download")
    
    report_service = ReportService(db)
    
    # 보고서 조회
    report = await report_service.get_report(report_id)
    if not report:
        raise ResourceNotFoundException("Report", report_id)
    
    # 권한 확인
    if report.partner_id != partner_id:
        try:
            await verify_permissions("reports.admin")
        except:
            raise ForbiddenException("You can only download your own reports")
    
    # 보고서 상태 확인
    if report.status != 'completed':
        raise InvalidRequestException(f"Report is not available for download. Current status: {report.status}")
    
    # 보고서 파일 가져오기
    file_content, filename = await report_service.get_report_file(report_id)
    if not file_content:
        raise ResourceNotFoundException("Report file", report_id)
    
    # MIME 타입 결정
    content_type = "application/octet-stream"  # 기본값
    if report.format == ReportExportFormat.CSV:
        content_type = "text/csv"
    elif report.format == ReportExportFormat.EXCEL:
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif report.format == ReportExportFormat.PDF:
        content_type = "application/pdf"
    elif report.format == ReportExportFormat.JSON:
        content_type = "application/json"
    
    # 다운로드 로깅
    logger.info(f"Report downloaded: {report_id} by partner {partner_id}")
    
    # 파일 다운로드 응답
    return Response(
        content=file_content,
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )

@router.get("/settlements", response_model=SettlementList)
async def list_settlements(
    date_range: dict = Depends(parse_date_range),
    status: Optional[str] = Query(None, description="상태로 필터링 (pending, processed, canceled)"),
    pagination: dict = Depends(common_pagination_params),
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id)
):
    """
    정산 목록 조회
    
    파트너는 자신의 정산 정보만 볼 수 있습니다.
    """
    # 정산 조회 권한 확인
    await verify_permissions("settlements.read")
    
    settlement_service = SettlementService(db)
    
    # 정산 목록 조회
    settlements, total = await settlement_service.list_settlements(
        partner_id=partner_id,
        start_date=date_range["start_date"],
        end_date=date_range["end_date"],
        status=status,
        skip=pagination["skip"],
        limit=pagination["limit"]
    )
    
    # 응답 생성
    items = []
    for settlement in settlements:
        items.append(SettlementResponse(
            id=settlement.id,
            partner_id=settlement.partner_id,
            period_start=settlement.period_start,
            period_end=settlement.period_end,
            status=settlement.status,
            amount=settlement.amount,
            currency=settlement.currency,
            settlement_date=settlement.settlement_date,
            created_at=settlement.created_at,
            updated_at=settlement.updated_at,
            details=settlement.details
        ))
    
    return SettlementList(
        items=items,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"]
    )

@router.get("/settlements/{settlement_id}", response_model=SettlementResponse)
async def get_settlement(
    settlement_id: str = Path(..., description="정산 ID"),
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id)
):
    """
    정산 세부 정보 조회
    
    파트너는 자신의 정산 정보만 볼 수 있습니다.
    """
    # 정산 조회 권한 확인
    await verify_permissions("settlements.read")
    
    settlement_service = SettlementService(db)
    
    # 정산 조회
    settlement = await settlement_service.get_settlement(settlement_id)
    if not settlement:
        raise ResourceNotFoundException("Settlement", settlement_id)
    
    # 권한 확인
    if settlement.partner_id != partner_id:
        try:
            await verify_permissions("settlements.admin")
        except:
            raise ForbiddenException("You can only view your own settlements")
    
    return SettlementResponse(
        id=settlement.id,
        partner_id=settlement.partner_id,
        period_start=settlement.period_start,
        period_end=settlement.period_end,
        status=settlement.status,
        amount=settlement.amount,
        currency=settlement.currency,
        settlement_date=settlement.settlement_date,
        created_at=settlement.created_at,
        updated_at=settlement.updated_at,
        details=settlement.details
    )