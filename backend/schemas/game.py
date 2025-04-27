"""
Pydantic 스키마 - 게임 관련
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, HttpUrl, validator, root_validator
from backend.models.enums import GameStatus, GameCategory
from decimal import Decimal

# --- Remove unnecessary import ---
# from backend.schemas.provider import GameProviderResponse # Assuming provider schemas are here
# --- End removal ---

class GameBase(BaseModel):
    # Fields common to Create and Response, reflecting the Game model structure
    name: str = Field(..., description="게임 이름", max_length=200)
    category: Optional[GameCategory] = Field(None, description="게임 카테고리")
    status: GameStatus = Field(default=GameStatus.ACTIVE, description="게임 상태")
    game_code: str = Field(..., description="게임 제공사 내부 코드", max_length=100)
    provider_id: UUID = Field(..., description="게임 제공자 ID")

    # Optional fields from model
    rtp: Optional[Decimal] = Field(None, description="RTP 백분율", ge=0, le=100)
    min_bet: Optional[Decimal] = Field(None, description="최소 베팅 금액", ge=0)
    max_bet: Optional[Decimal] = Field(None, description="최대 베팅 금액", ge=0)
    features: Optional[List[str]] = Field(None, description="게임 특징 목록 (예: [\"freespins\"])")
    description: Optional[str] = Field(None, description="게임 설명")
    thumbnail_url: Optional[HttpUrl] = Field(None, description="썸네일 이미지 URL")
    banner_url: Optional[HttpUrl] = Field(None, description="배너 이미지 URL")
    demo_url: Optional[HttpUrl] = Field(None, description="데모 플레이 URL")
    supported_currencies: Optional[List[str]] = Field(None, description="지원 통화 목록 (ISO 4217 코드)")
    supported_languages: Optional[List[str]] = Field(None, description="지원 언어 목록 (ISO 639-1 코드)")
    platform_compatibility: Optional[List[str]] = Field(None, description="호환 플랫폼 목록 (예: [\"desktop\"])")
    launch_date: Optional[datetime] = Field(None, description="게임 출시일")

    model_config = ConfigDict(from_attributes=True) # Keep for potential ORM mode use in subclasses

class GameCreate(GameBase):
    # Inherits all fields from GameBase
    # Add any fields specific to creation that are not in GameBase (if any)
    pass # GameBase now includes most necessary fields

class GameUpdate(BaseModel):
    # All fields are optional for partial updates
    name: Optional[str] = Field(None, description="게임 이름", max_length=200)
    category: Optional[GameCategory] = Field(None, description="게임 카테고리")
    status: Optional[GameStatus] = Field(None, description="게임 상태")
    # provider_id and game_code usually shouldn't be updated? Or depends on policy.
    # provider_id: Optional[UUID] = Field(None, description="게임 제공자 ID")
    # game_code: Optional[str] = Field(None, description="게임 제공사 내부 코드", max_length=100)
    rtp: Optional[Decimal] = Field(None, description="RTP 백분율", ge=0, le=100)
    min_bet: Optional[Decimal] = Field(None, description="최소 베팅 금액", ge=0)
    max_bet: Optional[Decimal] = Field(None, description="최대 베팅 금액", ge=0)
    features: Optional[List[str]] = Field(None, description="게임 특징 목록")
    description: Optional[str] = Field(None, description="게임 설명")
    thumbnail_url: Optional[HttpUrl] = Field(None, description="썸네일 이미지 URL")
    banner_url: Optional[HttpUrl] = Field(None, description="배너 이미지 URL")
    demo_url: Optional[HttpUrl] = Field(None, description="데모 플레이 URL")
    supported_currencies: Optional[List[str]] = Field(None, description="지원 통화 목록")
    supported_languages: Optional[List[str]] = Field(None, description="지원 언어 목록")
    platform_compatibility: Optional[List[str]] = Field(None, description="호환 플랫폼 목록")
    launch_date: Optional[datetime] = Field(None, description="게임 출시일")

    model_config = ConfigDict(extra='ignore') # Prevent arbitrary fields

class GameSessionBase(BaseModel):
    player_id: UUID
    game_id: UUID
    partner_id: UUID
    launch_url: Optional[str] = None # 게임 실행 URL
    status: str = Field("active", description="세션 상태 (active, closed)")

class GameSessionCreate(GameSessionBase):
    pass

class GameSession(GameSessionBase):
    id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class GameSessionList(BaseModel):
    items: List[GameSession]
    total: int
    page: int
    page_size: int

# --- Move Provider Schemas Before Game Schema ---
class GameProviderResponse(BaseModel):
    """ 게임 제공자 응답 스키마 """
    id: UUID
    name: str
    integration_type: str # direct, aggregator 등
    status: str # active, inactive 등
    api_url: Optional[str] = None # 관리자만 접근 가능

class GameProviderList(BaseModel):
    """ 게임 제공자 목록 응답 스키마 """
    items: List[GameProviderResponse]
    total: int
    page: int
    page_size: int

class GameProviderBase(BaseModel):
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=200)
    status: GameStatus = Field(default=GameStatus.ACTIVE)
    # ... other fields ...

    # Add model_config
    model_config = ConfigDict(from_attributes=True)

class GameProvider(GameProviderBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    # games: List[Game] = [] # Avoid circular dependency if possible
    model_config = ConfigDict(from_attributes=True)
# --- End Moving Provider Schemas ---

class Game(GameBase):
    # This is the Response Schema, inheriting common fields from GameBase
    id: UUID
    created_at: datetime
    updated_at: datetime
    provider: Optional[GameProviderResponse] = None # Embed provider info
    model_config = ConfigDict(from_attributes=True)

class GameList(BaseModel):
    items: List[Game]
    total: int
    page: int
    page_size: int

# --- Game Launch Schemas ---

class GameLaunchRequest(BaseModel):
    """ 게임 실행 요청 스키마 """
    game_id: UUID
    player_id: UUID
    partner_id: UUID
    currency: str = Field(..., min_length=3, max_length=3)
    language: Optional[str] = Field("en", min_length=2, max_length=10)
    return_url: Optional[HttpUrl] = None
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    session_data: Optional[Dict[str, Any]] = None
    device_info: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "game_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
                "player_id": "p12345",
                "partner_id": "partner_xyz",
                "currency": "USD",
                "language": "en",
                "return_url": "https://partner.com/return",
                "session_id": "partner_session_789",
                "ip_address": "192.168.1.100"
            }
        }
    )

class GameLaunchResponse(BaseModel):
    """ 게임 실행 응답 스키마 """
    game_url: Optional[str] = None # 기존 필드 (호환성을 위해 Optional로 유지)
    launch_url: str # 필요한 필드 추가 (필수)
    token: str
    expires_at: datetime
    
    @root_validator(pre=True)
    def map_game_url_to_launch_url(cls, values):
        """필드명 호환성 처리: game_url을 launch_url로 매핑"""
        if 'game_url' in values and 'launch_url' not in values:
            values['launch_url'] = values['game_url']
        elif 'launch_url' not in values and 'game_url' not in values:
             # 둘 다 없는 경우 에러 처리 또는 기본값 설정
             raise ValueError("Either 'game_url' or 'launch_url' must be provided")
        return values

    # 모델 생성 후 game_url을 제거하고 싶다면 validator 사용 가능
    # @validator('game_url', always=True)
    # def remove_game_url(cls, v, values):
    #     # 이 validator는 launch_url이 설정된 *후*에 실행됨
    #     # launch_url이 있으면 game_url은 None으로 설정하여 응답에서 제외
    #     if 'launch_url' in values and values['launch_url']:
    #          return None
    #     return v # launch_url이 없으면 원래 game_url 유지 (오류 상황)

    class Config:
        from_attributes = True # ORM 모드 활성화

class GameCallbackRequest(BaseModel):
    token: str

# --- Remove Provider Schemas From Here ---
# class GameProviderResponse(BaseModel):
#     """ 게임 제공자 응답 스키마 """
#     id: UUID
#     name: str
#     integration_type: str # direct, aggregator 등
#     status: str # active, inactive 등
#     api_url: Optional[str] = None # 관리자만 접근 가능
#
# class GameProviderList(BaseModel):
#     """ 게임 제공자 목록 응답 스키마 """
#     items: List[GameProviderResponse]
#     total: int
#     page: int
#     page_size: int
#
# class GameProviderBase(BaseModel):
#     code: str = Field(..., max_length=50)
#     name: str = Field(..., max_length=200)
#     status: GameStatus = Field(default=GameStatus.ACTIVE)
#     # ... other fields ...
#
#     # Add model_config
#     model_config = ConfigDict(from_attributes=True)
#
# class GameProvider(GameProviderBase):
#     id: UUID
#     created_at: datetime
#     updated_at: datetime
#     # games: List[Game] = [] # Avoid circular dependency if possible
#     model_config = ConfigDict(from_attributes=True)
# --- End Removal ---

# Update models
# ... Update schemas ... 