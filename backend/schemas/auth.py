"""
Pydantic 스키마 - 인증 관련
"""
from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    """로그인 요청 스키마"""
    partner_code: str = Field(..., description="파트너 코드")
    api_key: str = Field(..., description="API 키")
    # 필요시 password 등 추가

class TokenResponse(BaseModel):
    """토큰 응답 스키마"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer" 