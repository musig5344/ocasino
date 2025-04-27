"""
AML 관련 Pydantic 스키마 정의
"""
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Dict, Any

from backend.models.aml import AlertStatus, AlertSeverity, AlertType # Enum 임포트

class AMLAlertBase(BaseModel):
    player_id: UUID
    partner_id: UUID
    alert_type: AlertType
    severity: AlertSeverity
    description: Optional[str] = None
    related_transaction_id: Optional[UUID] = None

class AMLAlertCreate(AMLAlertBase):
    """ AML 알림 생성 요청 스키마 """
    pass # Base와 동일, 필요시 필드 추가

class AlertStatusUpdate(BaseModel):
    """ 알림 상태 업데이트 요청 스키마 """
    alert_id: int
    new_status: AlertStatus
    notes: Optional[str] = None
    assigned_to: Optional[str] = None

class AMLAlertResponse(AMLAlertBase):
    """ AML 알림 응답 스키마 """
    id: int
    status: AlertStatus
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None
    assigned_to: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True

# TODO: AMLReport, AMLRiskProfile 등의 스키마도 필요에 따라 추가

# 임시로 빈 파일. 추후 스키마 정의 필요
# pass # pass 제거 