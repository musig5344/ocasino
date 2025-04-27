# backend/schemas/health.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from datetime import datetime

class DependencyStatus(BaseModel):
    name: str = Field(..., description="의존성 이름 (예: database, redis)")
    status: str = Field(..., description="의존성 상태 (예: ok, error)")

class HealthCheckResponse(BaseModel):
    status: str = Field("ok", description="전체 서비스 상태")
    timestamp: datetime = Field(..., description="상태 확인 시간 (UTC)")
    dependencies: List[DependencyStatus] = Field([], description="개별 의존성 상태 목록") 