"""
파트너 관련 API 및 데이터 스키마
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, EmailStr, field_validator, ValidationInfo

# TODO: Update this import when enums are moved (e.g., to backend.common.enums)
from backend.models.enums import PartnerType, PartnerStatus, CommissionModel

# --- Base Schemas --- 

class BaseSchema(BaseModel):
    class Config:
        from_attributes = True # Pydantic v2 uses from_attributes instead of orm_mode

# --- API Key Schemas --- 

class ApiKeyBase(BaseSchema):
    """API 키 기본 스키마"""
    name: str = Field(..., description="API 키 이름")
    permissions: List[str] = Field(default_factory=list, description="권한 목록")
    expires_at: Optional[datetime] = Field(None, description="만료 일시")

class ApiKeyCreate(ApiKeyBase):
    """API 키 생성 스키마"""
    pass

class ApiKey(ApiKeyBase):
    """API 키 응답 스키마"""
    id: UUID
    key: str = Field(..., description="API 키 (마스킹 처리됨)") # Or perhaps remove entirely?
    partner_id: UUID
    is_active: bool
    last_used_at: Optional[datetime] = None
    created_at: datetime

class ApiKeyWithSecret(ApiKey):
    """API 키 및 비밀키 응답 스키마 (생성 직후)"""
    key_secret: str = Field(..., description="API 비밀키 (보안을 위해 한 번만 반환)")

class ApiKeyList(BaseSchema):
    """API 키 목록 응답 스키마"""
    items: List[ApiKey]
    count: int

# --- Partner Setting Schemas --- 

class PartnerSettingBase(BaseSchema):
    """파트너 설정 기본 스키마"""
    setting_key: str = Field(..., alias='key', description="설정 키") # Use alias for potentially reserved 'key'
    setting_value: str = Field(..., alias='value', description="설정 값") # Use alias for potentially reserved 'value'
    value_type: str = Field(..., description="값의 데이터 타입 (e.g., string, int, float, bool, json)")
    description: Optional[str] = Field(None, description="설명")

class PartnerSettingCreate(PartnerSettingBase):
    """파트너 설정 생성/업데이트 스키마"""
    # No additional fields needed for creation/update based on API endpoint
    pass 

class PartnerSetting(PartnerSettingBase):
    """파트너 설정 응답 스키마"""
    id: UUID
    partner_id: UUID
    created_at: datetime
    updated_at: datetime

class PartnerSettingList(BaseSchema):
    """파트너 설정 목록 응답 스키마"""
    items: List[PartnerSetting]
    total: int # Renamed from count for consistency with PartnerList

# --- Partner IP Whitelist Schemas --- 

class PartnerIPBase(BaseSchema):
    """파트너 IP 기본 스키마"""
    ip_address: str = Field(..., description="IP 주소 또는 CIDR 블록")
    description: Optional[str] = Field(None, description="설명")

class PartnerIPCreate(PartnerIPBase):
    """파트너 IP 생성 스키마"""
    pass

class PartnerIP(PartnerIPBase):
    """파트너 IP 응답 스키마"""
    id: UUID
    partner_id: UUID
    created_at: datetime
    is_active: bool # Assuming there's an active status

class PartnerIPList(BaseSchema):
    """파트너 IP 목록 응답 스키마"""
    items: List[PartnerIP]
    total: int # Renamed from count

# --- Partner Schemas --- 

class PartnerBase(BaseSchema):
    """파트너 기본 스키마"""
    code: str = Field(..., min_length=3, max_length=50, description="고유 파트너 코드")
    name: str = Field(..., min_length=2, max_length=200, description="파트너 이름")
    partner_type: PartnerType = Field(..., description="파트너 유형")
    commission_model: CommissionModel = Field(..., description="수수료 모델")
    commission_rate: float = Field(..., gt=0, description="수수료율 (예: 0.15 for 15%)")
    
    # 선택적 필드
    contact_name: Optional[str] = Field(None, max_length=100)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(None, max_length=50)
    company_name: Optional[str] = Field(None, max_length=200)
    company_address: Optional[str] = None
    company_registration_number: Optional[str] = Field(None, max_length=100)
    contract_start_date: Optional[datetime] = None
    contract_end_date: Optional[datetime] = None

class PartnerCreate(PartnerBase):
    """파트너 생성 스키마"""
    status: PartnerStatus = PartnerStatus.PENDING
    
    @field_validator('contract_end_date')
    @classmethod
    def validate_contract_dates(cls, v: Optional[datetime], info: ValidationInfo) -> Optional[datetime]:
        start_date = info.data.get('contract_start_date')
        if v and start_date and v < start_date:
            raise ValueError('계약 종료일은 시작일보다 이후여야 합니다')
        return v

class PartnerUpdate(BaseSchema):
    """파트너 업데이트 스키마 (부분 업데이트)"""
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    status: Optional[PartnerStatus] = None
    commission_model: Optional[CommissionModel] = None
    commission_rate: Optional[float] = Field(None, gt=0)
    
    contact_name: Optional[str] = Field(None, max_length=100)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(None, max_length=50)
    company_name: Optional[str] = Field(None, max_length=200)
    company_address: Optional[str] = None
    company_registration_number: Optional[str] = Field(None, max_length=100)
    contract_start_date: Optional[datetime] = None
    contract_end_date: Optional[datetime] = None
    
    @field_validator('contract_end_date')
    @classmethod
    def validate_contract_dates(cls, v: Optional[datetime], info: ValidationInfo) -> Optional[datetime]:
        # Allow clearing the date by passing None
        if v is None: 
            return v
        # If start_date is also being updated, check against the new value
        start_date = info.data.get('contract_start_date') 
        # If start_date is not in the update payload, we need the existing value. 
        # This validator can't access the existing DB value easily.
        # Validation requiring existing state is better handled in the service layer.
        # Simple check: if both dates are provided in the update, ensure end >= start.
        if start_date and v < start_date: 
             raise ValueError('계약 종료일은 시작일보다 이후여야 합니다')
        return v

class Partner(PartnerBase):
    """파트너 응답 스키마"""
    id: UUID
    status: PartnerStatus
    created_at: datetime
    updated_at: datetime

class PartnerDetail(Partner):
    """파트너 상세 응답 스키마 (관련 정보 포함)"""
    # These fields might be populated based on query parameters or permissions
    settings: Optional[List[PartnerSetting]] = None
    api_keys: Optional[List[ApiKey]] = None
    allowed_ips: Optional[List[PartnerIP]] = None

class PartnerList(BaseSchema):
    """파트너 목록 응답 스키마"""
    items: List[Partner]
    total: int
    page: Optional[int] = None # Make optional if not always calculated
    page_size: Optional[int] = None # Make optional 