import logging
from typing import Dict, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from backend.models.domain.audit_log import AuditLog
# 주석 처리: AuditLogRepository 임포트
# from backend.repositories.audit_repository import AuditLogRepository
from backend.utils.request_context import get_request_context

logger = logging.getLogger(__name__)


class AuditLogService:
    def __init__(self, db: AsyncSession):
        self.db = db
        # 주석 처리: AuditLogRepository 인스턴스화
        # self.audit_repo = AuditLogRepository(db)
        pass # 임시

    async def create_audit_log(
        self,
        log_type: str,
        level: str,
        action: str,
        description: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        partner_id: Optional[UUID] = None,
        api_key_id: Optional[UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_path: Optional[str] = None,
        request_method: Optional[str] = None,
        status_code: Optional[int] = None,
        response_time_ms: Optional[int] = None,
        log_metadata: Optional[Dict[str, Any]] = None,
    ):
        """감사 로그를 생성하고 저장합니다."""
        
        context = get_request_context()

        audit_log = AuditLog(
            log_type=log_type,
            level=level,
            action=action,
            description=description,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id or context.get("user_id"),
            username=username or context.get("username"),
            partner_id=partner_id or context.get("partner_id"),
            api_key_id=api_key_id or context.get("api_key_id"),
            ip_address=ip_address or context.get("ip_address"),
            user_agent=user_agent or context.get("user_agent"),
            request_id=context.get("request_id"), # 컨텍스트에서 request_id 가져오기
            request_path=request_path or context.get("request_path"),
            request_method=request_method or context.get("request_method"),
            status_code=str(status_code) if status_code is not None else None,
            response_time_ms=response_time_ms,
            log_metadata=log_metadata or {},
        )
        
        # 주석 처리: 레포지토리를 통한 저장
        # await self.audit_repo.create(audit_log)
        self.db.add(audit_log) # 임시: 직접 세션에 추가
        await self.db.flush() # 임시: ID 생성을 위해 flush
        logger.debug(f"Audit log created: {audit_log.id}")
        return audit_log

    async def log_request(
        self,
        ip_address: str,
        endpoint: str,
        method: str,
        partner_id: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None
    ) -> None:
        """요청 로그 기록"""
        audit_log = AuditLog(
            partner_id=partner_id,
            ip_address=ip_address,
            endpoint=endpoint,
            method=method,
            request_headers=headers,
            request_body=body
        )
        self.db.add(audit_log)
        self.db.commit()

    async def log_response(
        self,
        ip_address: str,
        endpoint: str,
        method: str,
        status_code: int,
        response_time: float,
        partner_id: Optional[str] = None
    ) -> None:
        """응답 로그 기록"""
        audit_log = self.db.query(AuditLog).filter(
            AuditLog.ip_address == ip_address,
            AuditLog.endpoint == endpoint,
            AuditLog.method == method,
            AuditLog.partner_id == partner_id
        ).order_by(AuditLog.created_at.desc()).first()

        if audit_log:
            audit_log.response_status = str(status_code)
            audit_log.response_time = f"{response_time:.3f}s"
            self.db.commit() 