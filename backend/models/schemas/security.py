from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

# Remove IPWhitelist schemas, they are defined in partners/schemas.py
# class IPWhitelistCreate(BaseModel):
#     ip_address: str = Field(..., description="IP 주소 또는 CIDR")
#     description: Optional[str] = Field(None)

# class IPWhitelistResponse(BaseModel):
#     id: str
#     ip_address: str
#     description: Optional[str]
#     is_active: bool
#     created_at: str
#     updated_at: str

# Potentially keep security-related schemas here, or move them
# Example:
class SecurityEvent(BaseModel):
    event_type: str
    details: dict
    timestamp: str

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