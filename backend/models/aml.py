"""
AML 관련 데이터 모델 정의
(예: AML 분석 결과, 리스크 레벨 등)
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum as SQLEnum, Text, Float, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID, JSONB

from backend.db.database import Base
from backend.db.types import UUIDType, JSONType

# --- Enums ---

class AlertType(str, Enum):
    THRESHOLD = "threshold"
    PATTERN = "pattern"
    BLACKLIST = "blacklist"
    MANUAL = "manual"
    OTHER = "other"

class AlertStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    PENDING_REPORT = "pending_report"
    REPORTED = "reported"
    CLOSED_FALSE_POSITIVE = "closed_false_positive"
    CLOSED_ACTION_TAKEN = "closed_action_taken"
    CLOSED_NO_ACTION = "closed_no_action"

class AlertSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ReportType(str, Enum):
    SAR = "SAR" # Suspicious Activity Report
    CTR = "CTR" # Currency Transaction Report
    STR = "STR" # Suspicious Transaction Report (alternative to SAR)

class ReportingJurisdiction(str, Enum):
    US = "US"
    EU = "EU"
    UK = "UK"
    KR = "KR"
    GLOBAL = "GLOBAL"

# --- Models ---

class AMLRiskProfile(Base):
    """플레이어 AML 위험 프로필"""
    __tablename__ = "aml_risk_profiles"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    player_id = Column(UUIDType, nullable=False, unique=True, index=True)
    partner_id = Column(UUIDType, nullable=False, index=True)
    risk_score = Column(Float, default=0.0, nullable=False)
    risk_level = Column(String(50), default="low", nullable=False) # low, medium, high
    last_calculated_at = Column(DateTime, default=datetime.utcnow)
    
    # 통계 정보 (업데이트 필요)
    total_deposit = Column(Float, default=0.0)
    total_withdrawal = Column(Float, default=0.0)
    transaction_count = Column(Integer, default=0)
    avg_transaction_amount = Column(Float, default=0.0)
    
    # 추가 정보
    kyc_status = Column(String(50)) # verified, pending, rejected
    country_code = Column(String(2))
    is_pep = Column(Boolean, default=False) # Politically Exposed Person
    additional_data = Column("metadata", JSONType) # 타입을 JSONType으로 변경
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AMLTransaction(Base):
    """AML 분석이 수행된 트랜잭션 정보"""
    __tablename__ = "aml_transactions"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    transaction_id = Column(UUIDType, ForeignKey("transactions.id"), nullable=False, unique=True, index=True)
    player_id = Column(UUIDType, nullable=False, index=True)
    partner_id = Column(UUIDType, nullable=False, index=True)
    risk_score = Column(Float, nullable=False)
    risk_factors = Column(JSONType) # 타입을 JSONType으로 변경
    analysis_details = Column(JSONType) # 타입을 JSONType으로 변경
    
    # 분석 결과 요약 플래그
    is_large_transaction = Column(Boolean, default=False)
    is_suspicious_pattern = Column(Boolean, default=False)
    is_unusual_for_player = Column(Boolean, default=False)
    is_structuring_attempt = Column(Boolean, default=False)
    is_regulatory_report_required = Column(Boolean, default=False)
    
    alert_id = Column(Integer, ForeignKey("aml_alerts.id"), nullable=True) # 연결된 알림 ID
    
    created_at = Column(DateTime, default=datetime.utcnow)

    transaction = relationship("Transaction") # relationships 정의 (필요시)
    alert = relationship("AMLAlert")

class AMLAlert(Base):
    """AML 알림"""
    __tablename__ = "aml_alerts"

    id = Column(Integer, primary_key=True)
    player_id = Column(UUIDType, nullable=False, index=True)
    partner_id = Column(UUIDType, nullable=False, index=True)
    alert_type = Column(SQLEnum(AlertType), nullable=False)
    status = Column(SQLEnum(AlertStatus), default=AlertStatus.OPEN, nullable=False)
    severity = Column(SQLEnum(AlertSeverity), nullable=False)
    description = Column(Text)
    risk_score_at_alert = Column(Float)
    risk_factors_at_alert = Column(JSONType) # 타입을 JSONType으로 변경
    related_transaction_id = Column(UUIDType, ForeignKey("transactions.id"), nullable=True)
    assigned_to = Column(String(100), nullable=True) # 담당자 ID
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    notes = Column(Text) # 조사 노트

    transaction = relationship("Transaction")

class AMLReport(Base):
    """AML 보고서 (SAR, CTR 등)"""
    __tablename__ = "aml_reports"
    
    id = Column(Integer, primary_key=True)
    report_id = Column(String(100), unique=True, nullable=False, index=True) # 보고서 고유 ID
    report_type = Column(SQLEnum(ReportType), nullable=False)
    status = Column(String(50), default="draft", nullable=False) # draft, submitted, accepted, rejected
    jurisdiction = Column(SQLEnum(ReportingJurisdiction), nullable=False)
    related_alert_id = Column(Integer, ForeignKey("aml_alerts.id"), nullable=True)
    related_transaction_id = Column(UUIDType, ForeignKey("transactions.id"), nullable=True)
    report_data = Column(JSONType) # 타입을 JSONType으로 변경
    created_by = Column(String(100)) # 생성자 (system or user ID)
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    alert = relationship("AMLAlert")
    transaction = relationship("Transaction")

# 임시로 빈 파일로 생성. 추후 모델 정의 필요.
pass 