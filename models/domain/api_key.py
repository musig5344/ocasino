"""
API 키 관련 도메인 모델
API 인증 및 권한 관리를 위한 모델
"""
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, List

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID
from sqlalchemy.orm import relationship

from backend.db.database import Base

class ApiKey(Base):
    """API 키 모델"""
    __tablename__ = "api_keys"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    partner_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("partners.id"), nullable=False)
    key = Column(String(100), unique=True, nullable=False, index=True)
    
    name = Column(String(100), nullable=False)
    description = Column(Text)
    permissions = Column(JSON, nullable=False, default=list)  # ["wallet:read", "wallet:write", ...]
    is_active = Column(Boolean, default=True)
    
    # 메타데이터
    created_by = Column(String(100))
    last_used_at = Column(DateTime)
    last_used_ip = Column(String(50))
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 관계
    partner = relationship("Partner", back_populates="api_keys")
    audit_logs = relationship("AuditLog", back_populates="api_key")
    
    def __repr__(self):
        return f"<ApiKey {self.name}: {self.key[:8]}...>"
    
    @property
    def is_expired(self) -> bool:
        """API 키가 만료되었는지 확인"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    @property
    def days_until_expiry(self) -> Optional[int]:
        """만료까지 남은 일 수"""
        if not self.expires_at:
            return None
        delta = self.expires_at - datetime.utcnow()
        return max(0, delta.days)
    
    def has_permission(self, required_permission: str) -> bool:
        """
        특정 권한이 있는지 확인
        
        Args:
            required_permission: 확인할 권한 (예: "wallet:read")
            
        Returns:
            bool: 권한 보유 여부
        """
        if not self.is_active or self.is_expired:
            return False
        
        # 모든 권한
        if "*" in self.permissions:
            return True
        
        # 특정 리소스의 모든 권한
        resource = required_permission.split(":")[0]
        if f"{resource}:*" in self.permissions:
            return True
        
        # 특정 권한
        return required_permission in self.permissions