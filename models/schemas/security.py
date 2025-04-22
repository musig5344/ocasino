from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class IPWhitelistCreate(BaseModel):
    ip_address: str
    partner_id: str
    description: Optional[str] = None

class IPWhitelistResponse(BaseModel):
    id: str
    ip_address: str
    partner_id: str
    description: Optional[str]
    is_active: bool
    created_at: datetime

class AuditLogResponse(BaseModel):
    id: str
    partner_id: Optional[str]
    ip_address: str
    endpoint: str
    method: str
    request_headers: Optional[dict]
    request_body: Optional[dict]
    response_status: str
    response_time: str
    created_at: datetime 