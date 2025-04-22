from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime

from models.domain.audit_log import AuditLog

class AuditService:
    def __init__(self, db: Session):
        self.db = db

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