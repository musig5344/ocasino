from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum
from decimal import Decimal

# --- Report Export Format ---
class ReportExportFormat(str, Enum):
    """보고서 내보내기 형식"""
    CSV = "csv"
    EXCEL = "xlsx"
    PDF = "pdf"
    JSON = "json"

# --- Report Type ---
class ReportParameterDefinition(BaseModel):
    """보고서 유형별 파라미터 정의"""
    name: str = Field(..., description="파라미터 이름")
    type: str = Field(..., description="파라미터 타입 (e.g., string, integer, date, boolean)")
    required: bool = Field(False, description="필수 여부")
    description: Optional[str] = Field(None, description="파라미터 설명")
    default: Optional[Any] = Field(None, description="기본값")
    options: Optional[List[Any]] = Field(None, description="선택 가능한 값 목록 (해당되는 경우)")

class ReportTypeResponse(BaseModel):
    """보고서 유형 응답 스키마"""
    id: str = Field(..., description="보고서 유형 ID")
    code: str = Field(..., description="보고서 유형 코드 (e.g., daily_summary, player_activity)")
    name: str = Field(..., description="보고서 유형 이름")
    description: Optional[str] = Field(None, description="보고서 유형 설명")
    available_formats: List[ReportExportFormat] = Field(..., description="사용 가능한 내보내기 형식")
    parameters: Optional[List[ReportParameterDefinition]] = Field(None, description="보고서 생성에 필요한 파라미터 정의")

class ReportTypeList(BaseModel):
    """보고서 유형 목록 응답 스키마"""
    items: List[ReportTypeResponse]
    count: int = Field(..., description="총 보고서 유형 수")

# --- Report Generation ---
class ReportCreate(BaseModel):
    """보고서 생성 요청 스키마"""
    report_type_id: str = Field(..., description="생성할 보고서 유형 ID")
    format: ReportExportFormat = Field(..., description="보고서 형식")
    parameters: Dict[str, Any] = Field({}, description="보고서 생성 파라미터 (키-값 쌍)")
    name: Optional[str] = Field(None, description="보고서 이름 (선택 사항, 미지정 시 자동 생성)")

# --- Report Status ---
class ReportStatus(str, Enum):
    """보고서 생성 상태"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# --- Report Response ---
class ReportResponse(BaseModel):
    """보고서 응답 스키마"""
    id: str = Field(..., description="보고서 ID")
    partner_id: str = Field(..., description="파트너 ID")
    report_type: Optional[ReportTypeResponse] = Field(None, description="보고서 유형 정보") # get_report 등에서 join해서 가져올 수 있음
    name: Optional[str] = Field(None, description="보고서 이름")
    status: ReportStatus = Field(..., description="보고서 생성 상태")
    format: ReportExportFormat = Field(..., description="보고서 형식")
    parameters: Optional[Dict[str, Any]] = Field(None, description="보고서 생성 파라미터")
    created_at: datetime = Field(..., description="보고서 요청 생성 시간")
    completed_at: Optional[datetime] = Field(None, description="보고서 생성 완료 시간")
    file_size: Optional[int] = Field(None, description="생성된 파일 크기 (바이트)")
    error_message: Optional[str] = Field(None, description="실패 시 오류 메시지")
    # download_url: Optional[str] = Field(None, description="다운로드 URL (생성 후 제공될 수 있음)") # 필요시 추가

class ReportList(BaseModel):
    """보고서 목록 응답 스키마"""
    items: List[ReportResponse]
    total: int = Field(..., description="총 보고서 수")
    page: int = Field(..., description="현재 페이지 번호")
    page_size: int = Field(..., description="페이지 당 항목 수")

# --- Settlement Status ---
class SettlementStatus(str, Enum):
    """정산 상태"""
    PENDING = "pending"       # 정산 대기
    PROCESSING = "processing" # 정산 처리 중
    PROCESSED = "processed"   # 정산 완료
    CANCELED = "canceled"     # 정산 취소
    FAILED = "failed"         # 정산 실패

# --- Settlement Response ---
class SettlementResponse(BaseModel):
    """정산 응답 스키마"""
    id: str = Field(..., description="정산 ID")
    partner_id: str = Field(..., description="파트너 ID")
    period_start: date = Field(..., description="정산 기간 시작일")
    period_end: date = Field(..., description="정산 기간 종료일")
    status: SettlementStatus = Field(..., description="정산 상태")
    amount: Decimal = Field(..., description="정산 금액")
    currency: str = Field(..., description="통화 코드")
    settlement_date: Optional[date] = Field(None, description="정산 처리일")
    created_at: datetime = Field(..., description="정산 레코드 생성 시간")
    updated_at: datetime = Field(..., description="정산 레코드 마지막 수정 시간")
    details: Optional[Dict[str, Any]] = Field(None, description="정산 세부 정보 (e.g., 수수료, 조정 내역)")

class SettlementList(BaseModel):
    """정산 목록 응답 스키마"""
    items: List[SettlementResponse]
    total: int = Field(..., description="총 정산 내역 수")
    page: int = Field(..., description="현재 페이지 번호")
    page_size: int = Field(..., description="페이지 당 항목 수") 