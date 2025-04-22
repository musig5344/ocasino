"""
파트너 관련 API 스키마
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, EmailStr, validator

from backend.models.domain.partner import PartnerType, PartnerStatus, CommissionModel

class ApiKeyBase(BaseModel):
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
    key: str
    partner_id: UUID
    is_active: bool
    last_used_at: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        orm_mode = True

class ApiKeyWithSecret(ApiKey):
    """API 키 및 비밀키 응답 스키마 (생성 직후)"""
    key_secret: str

class PartnerSettingBase(BaseModel):
    """파트너 설정 기본 스키마"""
    key: str
    value: str
    description: Optional[str] = None

class PartnerSettingCreate(PartnerSettingBase):
    """파트너 설정 생성 스키마"""
    pass

class PartnerSetting(PartnerSettingBase):
    """파트너 설정 응답 스키마"""
    id: UUID
    partner_id: UUID
    
    class Config:
        orm_mode = True

class PartnerIPBase(BaseModel):
    """파트너 IP 기본 스키마"""
    ip_address: str
    description: Optional[str] = None

class PartnerIPCreate(PartnerIPBase):
    """파트너 IP 생성 스키마"""
    pass

class PartnerIP(PartnerIPBase):
    """파트너 IP 응답 스키마"""
    id: UUID
    partner_id: UUID
    created_at: datetime
    
    class Config:
        orm_mode = True

class PartnerBase(BaseModel):
    """파트너 기본 스키마"""
    code: str = Field(..., min_length=3, max_length=50)
    name: str = Field(..., min_length=2, max_length=200)
    partner_type: PartnerType
    commission_model: CommissionModel
    commission_rate: str
    
    # 선택적 필드
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    company_name: Optional[str] = None
    company_address: Optional[str] = None
    company_registration_number: Optional[str] = None
    contract_start_date: Optional[datetime] = None
    contract_end_date: Optional[datetime] = None

class PartnerCreate(PartnerBase):
    """파트너 생성 스키마"""
    status: PartnerStatus = PartnerStatus.PENDING
    
    @validator('contract_end_date')
    def validate_contract_dates(cls, v, values):
        if v and 'contract_start_date' in values and values['contract_start_date']:
            if v < values['contract_start_date']:
                raise ValueError('종료일은 시작일보다 이후여야 합니다')
        return v

class PartnerUpdate(BaseModel):
    """파트너 업데이트 스키마"""
    name: Optional[str] = None
    status: Optional[PartnerStatus] = None
    commission_model: Optional[CommissionModel] = None
    commission_rate: Optional[str] = None
    
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None
    company_name: Optional[str] = None
    company_address: Optional[str] = None
    company_registration_number: Optional[str] = None
    contract_start_date: Optional[datetime] = None
    contract_end_date: Optional[datetime] = None
    
    @validator('contract_end_date')
    def validate_contract_dates(cls, v, values):
        if v and 'contract_start_date' in values and values['contract_start_date']:
            if v < values['contract_start_date']:
                raise ValueError('종료일은 시작일보다 이후여야 합니다')
        return v

class Partner(PartnerBase):
    """파트너 응답 스키마"""
    id: UUID
    status: PartnerStatus
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

class PartnerDetail(Partner):
    """파트너 상세 응답 스키마"""
    settings: List[PartnerSetting] = []
    api_keys: List[ApiKey] = []
    allowed_ips: List[PartnerIP] = []