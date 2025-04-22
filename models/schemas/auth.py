from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

class TokenPayload(BaseModel):
    sub: str
    exp: datetime

class APIKeyCreate(BaseModel):
    partner_id: str
    description: Optional[str] = None
    expires_at: Optional[datetime] = None

class APIKeyResponse(BaseModel):
    id: str
    key: str
    partner_id: str
    is_active: bool
    created_at: datetime
    expires_at: Optional[datetime] = None 