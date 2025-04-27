"""
게임 관련 도메인 모델
"""
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, List, Dict, Any
# from enum import Enum # Remove Enum import if no longer needed locally

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Numeric, JSON, Text, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID
from sqlalchemy.orm import relationship, validates

from backend.db.database import Base
from backend.db.types import UUIDType, GUID, JSONType
from backend.models.enums import GameCategory, GameStatus # Add import from enums

# REMOVE GameCategory definition
# // ... existing code ... (Comment out or delete the GameCategory class block)
# class GameCategory(str, Enum): ...

# REMOVE GameStatus definition
# // ... existing code ... (Comment out or delete the GameStatus class block)
# class GameStatus(str, Enum): ...

class GameProvider(Base):
    """게임 제공자 모델"""
    __tablename__ = "game_providers"
    
    id = Column(GUID, primary_key=True, default=uuid4)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    status = Column(SQLEnum(GameStatus), nullable=False, default=GameStatus.ACTIVE) # Use imported GameStatus
    is_active = Column(Boolean, default=True, nullable=False)
    
    # 통합 설정
    integration_type = Column(String(50))  # "direct", "aggregator", "iframe"
    api_endpoint = Column(String(255))
    api_key = Column(String(255))
    api_secret = Column(String(255))
    
    # 메타데이터
    description = Column(Text)
    logo_url = Column(String(255))
    website = Column(String(255))
    supported_currencies = Column(JSONType)
    supported_languages = Column(JSONType)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    games = relationship("Game", back_populates="provider")
    
    def __repr__(self):
        return f"<GameProvider {self.code}: {self.name}>"

class Game(Base):
    """게임 모델"""
    __tablename__ = "games"
    
    id = Column(GUID, primary_key=True, default=uuid4)
    provider_id = Column(GUID, ForeignKey("game_providers.id"), nullable=False, index=True)
    game_code = Column(String(100), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    
    category = Column(SQLEnum(GameCategory), nullable=False) # Use imported GameCategory
    status = Column(SQLEnum(GameStatus), nullable=False, default=GameStatus.ACTIVE) # Use imported GameStatus
    
    # 게임 설정
    rtp = Column(Numeric(precision=5, scale=2))  # Return to Player 퍼센트 (95.5%)
    min_bet = Column(Numeric(precision=18, scale=2))
    max_bet = Column(Numeric(precision=18, scale=2))
    features = Column(JSONType)  # ["freespins", "bonus", "jackpot"]
    
    # 미디어 및 정보
    description = Column(Text)
    thumbnail_url = Column(String(255))
    banner_url = Column(String(255))
    demo_url = Column(String(255))
    
    # 메타데이터
    supported_currencies = Column(JSONType)
    supported_languages = Column(JSONType)
    platform_compatibility = Column(JSONType)  # ["desktop", "mobile", "tablet"]
    launch_date = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    provider = relationship("GameProvider", back_populates="games")
    sessions = relationship("GameSession", back_populates="game")
    
    # 복합 인덱스: provider_id + game_code
    __table_args__ = (
        Index('ix_game_provider_code', 'provider_id', 'game_code', unique=True),
    )
    
    def __repr__(self):
        return f"<Game {self.game_code}: {self.name}>"

class GameSession(Base):
    """게임 세션 모델"""
    __tablename__ = "game_sessions"
    
    id = Column(GUID, primary_key=True, default=uuid4)
    player_id = Column(GUID, nullable=False, index=True)
    partner_id = Column(GUID, ForeignKey("partners.id"), nullable=False, index=True)
    game_id = Column(GUID, ForeignKey("games.id"), nullable=False, index=True)
    
    token = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(String(20), default="active")  # "active", "ended", "expired"
    
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime)
    
    player_ip = Column(String(50))
    device_info = Column(JSONType)
    session_data = Column(JSONType)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    game = relationship("Game", back_populates="sessions")
    transactions = relationship("GameTransaction", back_populates="session")
    
    # Add UniqueConstraint for active sessions per player per game
    __table_args__ = (
        Index(
            'ix_active_player_game_session',
            'player_id', 
            'game_id', 
            'status',
            unique=True,
            postgresql_where=text("status = 'active'")
        ),
        # 다른 인덱스가 필요하다면 여기에 추가
    )
    
    def __repr__(self):
        return f"<GameSession {self.token}: {self.status}>"

class GameTransaction(Base):
    """게임 트랜잭션 모델"""
    __tablename__ = "game_transactions"
    
    id = Column(UUIDType, primary_key=True, default=uuid4)
    session_id = Column(UUIDType, ForeignKey("game_sessions.id"), nullable=False)
    transaction_id = Column(UUIDType, ForeignKey("transactions.id"), nullable=True)
    
    reference_id = Column(String(100), unique=True, nullable=False, index=True)
    round_id = Column(String(100), index=True)
    
    action = Column(String(20), nullable=False)  # "bet", "win", "refund"
    amount = Column(Numeric(precision=18, scale=2), nullable=False)
    currency = Column(String(3), nullable=False)
    
    game_data = Column(JSONType)
    provider_transaction_id = Column(String(100))
    
    status = Column(String(20), nullable=False, default="pending")  # "pending", "completed", "failed", "canceled"
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    session = relationship("GameSession", back_populates="transactions")
    
    def __repr__(self):
        return f"<GameTransaction {self.reference_id}: {self.amount} {self.currency} ({self.action})>"