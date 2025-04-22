"""
파트너 관련 도메인 모델
"""
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, List
from enum import Enum

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Text, JSON
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID
from sqlalchemy.orm import relationship

from backend.db.database import Base

class PartnerType(str, Enum):
    """파트너 유형"""
    CASINO_OPERATOR = "casino_operator"      # 카지노 운영사
    GAME_AGGREGATOR = "game_aggregator"      # 게임 어그리게이터
    AFFILIATE = "affiliate"                  # 제휴사
    PAYMENT_PROVIDER = "payment_provider"    # 결제 서비스 제공사

class PartnerStatus(str, Enum):
    """파트너 상태"""
    ACTIVE = "active"            # 활성화
    PENDING = "pending"          # 대기 중
    SUSPENDED = "suspended"      # 일시 정지
    TERMINATED = "terminated"    # 계약 종료

class CommissionModel(str, Enum):
    """수수료 모델"""
    TRANSACTION_FEE = "transaction_fee"    # 거래량 기반 수수료
    REVENUE_SHARE = "revenue_share"        # 수익 공유 모델
    SUBSCRIPTION = "subscription"          # 월 구독료
    HYBRID = "hybrid"                      # 혼합 모델

class Partner(Base):
    """파트너 모델"""
    __tablename__ = "partners"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    partner_type = Column(SQLEnum(PartnerType), nullable=False)
    status = Column(SQLEnum(PartnerStatus), nullable=False, default=PartnerStatus.PENDING)
    
    # 연락처 정보
    contact_name = Column(String(100))
    contact_email = Column(String(150))
    contact_phone = Column(String(50))
    
    # 사업 정보
    company_name = Column(String(200))
    company_address = Column(Text)
    company_registration_number = Column(String(100))
    
    # 계약 정보
    commission_model = Column(SQLEnum(CommissionModel), nullable=False)
    commission_rate = Column(String(50))  # 형식: "0.25%" 또는 "10 USD per transaction"
    contract_start_date = Column(DateTime)
    contract_end_date = Column(DateTime)
    
    # 메타데이터
    settings = relationship("PartnerSetting", back_populates="partner", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="partner", cascade="all, delete-orphan")
    wallets = relationship("Wallet", back_populates="partner")
    allowed_ips = relationship("PartnerIP", back_populates="partner", cascade="all, delete-orphan")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Partner {self.code}: {self.name}>"

class ApiKey(Base):
    """API 키 모델"""
    __tablename__ = "api_keys"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    partner_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("partners.id"), nullable=False)
    key = Column(String(100), unique=True, nullable=False, index=True)
    
    name = Column(String(100), nullable=False)
    permissions = Column(JSON, nullable=False, default=list)  # ["wallet:read", "wallet:write", ...]
    is_active = Column(Boolean, default=True)
    
    last_used_at = Column(DateTime)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    partner = relationship("Partner", back_populates="api_keys")
    
    def __repr__(self):
        return f"<ApiKey {self.name}: {self.key[:8]}...>"

class PartnerSetting(Base):
    """파트너 설정 모델"""
    __tablename__ = "partner_settings"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    partner_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("partners.id"), nullable=False)
    key = Column(String(100), nullable=False)
    value = Column(Text, nullable=False)
    description = Column(String(255))
    
    # 복합 인덱스: partner_id + key
    __table_args__ = (
        sqlalchemy.UniqueConstraint('partner_id', 'key', name='uix_partner_setting'),
    )
    
    partner = relationship("Partner", back_populates="settings")
    
    def __repr__(self):
        return f"<PartnerSetting {self.key}: {self.value[:30]}...>"

class PartnerIP(Base):
    """파트너 허용 IP 모델"""
    __tablename__ = "partner_ips"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    partner_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("partners.id"), nullable=False)
    ip_address = Column(String(50), nullable=False)
    description = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 복합 인덱스: partner_id + ip_address
    __table_args__ = (
        sqlalchemy.UniqueConstraint('partner_id', 'ip_address', name='uix_partner_ip'),
    )
    
    partner = relationship("Partner", back_populates="allowed_ips")
    
    def __repr__(self):
        return f"<PartnerIP {self.ip_address}>"