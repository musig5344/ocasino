"""
감사 로그 관련 도메인 모델
시스템 작업 추적 및 규제 준수를 위한 모델
"""
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum

from sqlalchemy import Column, String, DateTime, ForeignKey, Enum as SQLEnum, JSON, Text, Index
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID
from sqlalchemy.orm import relationship

from backend.db.database import Base

class AuditLogLevel(str, Enum):
    """감사 로그 수준"""
    INFO = "info"           # 일반 정보성 이벤트
    NOTICE = "notice"       # 주목할 만한 이벤트
    WARNING = "warning"     # 잠재적 문제
    ALERT = "alert"         # 즉각적 조치 필요
    CRITICAL = "critical"   # 심각한 문제

class AuditLogType(str, Enum):
    """감사 로그 유형"""
    LOGIN = "login"                   # 로그인
    LOGOUT = "logout"                 # 로그아웃
    API_ACCESS = "api_access"         # API 접근
    RESOURCE_CREATE = "resource_create"  # 리소스 생성
    RESOURCE_READ = "resource_read"      # 리소스 읽기
    RESOURCE_UPDATE = "resource_update"  # 리소스 수정
    RESOURCE_DELETE = "resource_delete"  # 리소스 삭제
    SYSTEM = "system"                 # 시스템 이벤트
    SECURITY = "security"             # 보안 이벤트
    TRANSACTION = "transaction"       # 금융 거래

class AuditLog(Base):
    """감사 로그 모델"""
    __tablename__ = "audit_logs"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # 작업 정보
    log_type = Column(SQLEnum(AuditLogType), nullable=False, index=True)
    level = Column(SQLEnum(AuditLogLevel), nullable=False, default=AuditLogLevel.INFO)
    action = Column(String(100), nullable=False)
    description = Column(Text)
    
    # 리소스 정보
    resource_type = Column(String(50), index=True)
    resource_id = Column(String(100), index=True)
    
    # 사용자/시스템 정보
    user_id = Column(String(100), index=True)
    username = Column(String(100))
    partner_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("partners.id"), index=True)
    api_key_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("api_keys.id"), index=True)
    
    # 요청 정보
    ip_address = Column(String(50))
    user_agent = Column(String(255))
    request_id = Column(String(50), index=True)
    request_path = Column(String(255))
    request_method = Column(String(10))
    
    # 추가 정보
    status_code = Column(String(10))
    response_time_ms = Column(Integer)
    metadata = Column(JSON)
    
    # 관계
    partner = relationship("Partner", back_populates="audit_logs")
    api_key = relationship("ApiKey", back_populates="audit_logs")
    
    __table_args__ = (
        # 파트너별 날짜별 인덱스 (로그 검색 최적화)
        Index('ix_audit_logs_partner_date', partner_id, 
              text("date_trunc('day', timestamp)")),
    )
    
    def __repr__(self):
        return f"<AuditLog {self.id}: {self.action} ({self.level})>"
    
    @classmethod
    def create_from_request(cls, request, action: str, log_type: AuditLogType, 
                         level: AuditLogLevel = AuditLogLevel.INFO, 
                         resource_type: Optional[str] = None,
                         resource_id: Optional[str] = None,
                         description: Optional[str] = None,
                         metadata: Optional[Dict[str, Any]] = None):
        """
        HTTP 요청에서 감사 로그 생성
        
        Args:
            request: FastAPI 요청 객체
            action: 수행된 작업
            log_type: 로그 유형
            level: 로그 수준
            resource_type: 리소스 유형
            resource_id: 리소스 ID
            description: 설명
            metadata: 추가 메타데이터
            
        Returns:
            AuditLog: 생성된 감사 로그
        """
        # 사용자 정보 추출
        user_id = getattr(request.state, "user_id", None)
        username = getattr(request.state, "username", None)
        partner_id = getattr(request.state, "partner_id", None)
        api_key_id = getattr(request.state, "api_key_id", None)
        
        return cls(
            log_type=log_type,
            level=level,
            action=action,
            description=description,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            username=username,
            partner_id=partner_id,
            api_key_id=api_key_id,
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent"),
            request_id=getattr(request.state, "request_id", None),
            request_path=request.url.path,
            request_method=request.method,
            metadata=metadata or {}
        )