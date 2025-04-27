from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, UUID, datetime

class AuditLogBase(BaseModel):
    log_type: AuditLogType
    level: AuditLogLevel = AuditLogLevel.INFO
    action: str = Field(..., max_length=100)
    description: Optional[str] = None
    # ... other fields ...

    # Add model_config
    model_config = ConfigDict(from_attributes=True)

class AuditLogCreate(AuditLogBase):
    pass # Inherits config from Base

class AuditLog(AuditLogBase):
    id: UUID
    timestamp: datetime

    # Add model_config
    model_config = ConfigDict(from_attributes=True)

# ... other schemas ... 