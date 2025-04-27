"""
게임 관련 API 스키마
"""
from typing import List, Optional, Dict, Any, Set
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, Field, HttpUrl, validator

from backend.models.domain.game import GameCategory, GameStatus

class GameProviderBase(BaseModel):
    """게임 제공자 기본 스키마"""
    code: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=2, max_length=200)
    integration_type: str = Field(..., description="Direct, Aggregator, IFrame 등")
    
    # 선택적 필드
    api_endpoint: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[HttpUrl] = None
    website: Optional[HttpUrl] = None
    supported_currencies: Optional[List[str]] = None
    supported_languages: Optional[List[str]] = None

class GameProviderCreate(GameProviderBase):
    """게임 제공자 생성 스키마"""
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    status: GameStatus = GameStatus.ACTIVE

class GameProviderUpdate(BaseModel):
    """게임 제공자 업데이트 스키마"""
    name: Optional[str] = None
    status: Optional[GameStatus] = None
    integration_type: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[HttpUrl] = None
    website: Optional[HttpUrl] = None
    supported_currencies: Optional[List[str]] = None
    supported_languages: Optional[List[str]] = None

class GameProvider(GameProviderBase):
    """게임 제공자 응답 스키마"""
    id: UUID
    status: GameStatus
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

class GameBase(BaseModel):
    """게임 기본 스키마"""
    game_code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=2, max_length=200)
    category: GameCategory
    
    # 선택적 필드
    rtp: Optional[Decimal] = Field(None, ge=0, le=100)
    min_bet: Optional[Decimal] = Field(None, ge=0)
    max_bet: Optional[Decimal] = Field(None, ge=0)
    features: Optional[List[str]] = None
    description: Optional[str] = None
    thumbnail_url: Optional[HttpUrl] = None
    banner_url: Optional[HttpUrl] = None
    demo_url: Optional[HttpUrl] = None
    supported_currencies: Optional[List[str]] = None
    supported_languages: Optional[List[str]] = None
    platform_compatibility: Optional[List[str]] = None
    launch_date: Optional[datetime] = None

class GameCreate(GameBase):
    """게임 생성 스키마"""
    provider_id: UUID
    status: GameStatus = GameStatus.ACTIVE
    
    @validator('max_bet')
    def validate_bet_limits(cls, v, values):
        if 'min_bet' in values and v is not None and values['min_bet'] is not None:
            if v < values['min_bet']:
                raise ValueError('최대 베팅은 최소 베팅보다 커야 합니다')
        return v

class GameUpdate(BaseModel):
    """게임 업데이트 스키마"""
    name: Optional[str] = None
    category: Optional[GameCategory] = None
    status: Optional[GameStatus] = None
    rtp: Optional[Decimal] = Field(None, ge=0, le=100)
    min_bet: Optional[Decimal] = Field(None, ge=0)
    max_bet: Optional[Decimal] = Field(None, ge=0)
    features: Optional[List[str]] = None
    description: Optional[str] = None
    thumbnail_url: Optional[HttpUrl] = None
    banner_url: Optional[HttpUrl] = None
    demo_url: Optional[HttpUrl] = None
    supported_currencies: Optional[List[str]] = None
    supported_languages: Optional[List[str]] = None
    platform_compatibility: Optional[List[str]] = None
    
    @validator('max_bet')
    def validate_bet_limits(cls, v, values):
        if 'min_bet' in values and v is not None and values['min_bet'] is not None:
            if v < values['min_bet']:
                raise ValueError('최대 베팅은 최소 베팅보다 커야 합니다')
        return v

class Game(GameBase):
    """게임 응답 스키마"""
    id: UUID
    provider_id: UUID
    status: GameStatus
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

class GameDetail(Game):
    """게임 상세 응답 스키마"""
    provider: GameProvider
    
    class Config:
        orm_mode = True

class GameSessionBase(BaseModel):
    """게임 세션 기본 스키마"""
    player_id: UUID
    game_id: UUID
    
    # 선택적 필드
    player_ip: Optional[str] = None
    device_info: Optional[Dict[str, Any]] = None
    session_data: Optional[Dict[str, Any]] = None

class GameSessionCreate(GameSessionBase):
    """게임 세션 생성 스키마"""
    pass

class GameSession(GameSessionBase):
    """게임 세션 응답 스키마"""
    id: UUID
    partner_id: UUID
    token: str
    status: str
    start_time: datetime
    end_time: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

class GameLaunchRequest(BaseModel):
    """게임 실행 요청 스키마"""
    player_id: UUID
    game_id: UUID
    currency: str = Field(..., min_length=3, max_length=3)
    language: Optional[str] = "en"
    return_url: Optional[HttpUrl] = None
    
    class Config:
        schema_extra = {
            "example": {
                "player_id": "123e4567-e89b-12d3-a456-426614174000",
                "game_id": "123e4567-e89b-12d3-a456-426614174000",
                "currency": "USD",
                "language": "en",
                "return_url": "https://example.com/lobby"
            }
        }

class GameLaunchResponse(BaseModel):
    """게임 실행 응답 스키마"""
    game_url: HttpUrl
    token: str
    expires_at: datetime
    
    class Config:
        schema_extra = {
            "example": {
                "game_url": "https://games.example.com/play?token=abc123",
                "token": "abc123",
                "expires_at": "2023-03-01T13:00:00Z"
            }
        }