"""
게임 관련 도메인 모델
"""
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Numeric, JSON, Text, Index
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID
from sqlalchemy.orm import relationship

from backend.db.database import Base

class GameCategory(str, Enum):
    """게임 카테고리"""
    SLOTS = "slots"              # 슬롯 머신
    TABLE_GAMES = "table_games"  # 테이블 게임
    LIVE_CASINO = "live_casino"  # 라이브 카지노
    POKER = "poker"              # 포커
    BINGO = "bingo"              # 빙고
    LOTTERY = "lottery"          # 로또
    SPORTS = "sports"            # 스포츠 베팅
    ARCADE = "arcade"            # 아케이드

class GameStatus(str, Enum):
    """게임 상태"""
    ACTIVE = "active"            # 활성화
    MAINTENANCE = "maintenance"  # 유지보수
    DISABLED = "disabled"        # 비활성화
    DEPRECATED = "deprecated"    # 지원 종료

class GameProvider(Base):
    """게임 제공자 모델"""
    __tablename__ = "game_providers"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    status = Column(SQLEnum(GameStatus), nullable=False, default=GameStatus.ACTIVE)
    
    # 통합 설정
    integration_type = Column(String(50))  # "direct", "aggregator", "iframe"
    api_endpoint = Column(String(255))
    api_key = Column(String(255))
    api_secret = Column(String(255))
    
    # 메타데이터
    description = Column(Text)
    logo_url = Column(String(255))
    website = Column(String(255))
    supported_currencies = Column(JSON)
    supported_languages = Column(JSON)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    games = relationship("Game", back_populates="provider")
    
    def __repr__(self):
        return f"<GameProvider {self.code}: {self.name}>"

class Game(Base):
    """게임 모델"""
    __tablename__ = "games"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    provider_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("game_providers.id"), nullable=False)
    game_code = Column(String(100), nullable=False)
    name = Column(String(200), nullable=False)
    
    category = Column(SQLEnum(GameCategory), nullable=False)
    status = Column(SQLEnum(GameStatus), nullable=False, default=GameStatus.ACTIVE)
    
    # 게임 설정
    rtp = Column(Numeric(precision=5, scale=2))  # Return to Player 퍼센트 (95.5%)
    min_bet = Column(Numeric(precision=18, scale=2))
    max_bet = Column(Numeric(precision=18, scale=2))
    features = Column(JSON)  # ["freespins", "bonus", "jackpot"]
    
    # 미디어 및 정보
    description = Column(Text)
    thumbnail_url = Column(String(255))
    banner_url = Column(String(255))
    demo_url = Column(String(255))
    
    # 메타데이터
    supported_currencies = Column(JSON)
    supported_languages = Column(JSON)
    platform_compatibility = Column(JSON)  # ["desktop", "mobile", "tablet"]
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
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    player_id = Column(PSQL_UUID(as_uuid=True), nullable=False, index=True)
    partner_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("partners.id"), nullable=False)
    game_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("games.id"), nullable=False)
    
    token = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(String(20), default="active")  # "active", "ended", "expired"
    
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime)
    
    player_ip = Column(String(50))
    device_info = Column(JSON)
    session_data = Column(JSON)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    game = relationship("Game", back_populates="sessions")
    transactions = relationship("GameTransaction", back_populates="session")
    
    def __repr__(self):
        return f"<GameSession {self.token}: {self.status}>"

class GameTransaction(Base):
    """게임 트랜잭션 모델"""
    __tablename__ = "game_transactions"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("game_sessions.id"), nullable=False)
    transaction_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("transactions.id"))
    
    reference_id = Column(String(100), unique=True, nullable=False, index=True)
    round_id = Column(String(100), index=True)
    
    action = Column(String(20), nullable=False)  # "bet", "win", "refund"
    amount = Column(Numeric(precision=18, scale=2), nullable=False)
    currency = Column(String(3), nullable=False)
    
    game_data = Column(JSON)
    provider_transaction_id = Column(String(100))
    
    status = Column(String(20), nullable=False, default="pending")  # "pending", "completed", "failed", "canceled"
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    session = relationship("GameSession", back_populates="transactions")
    
    def __repr__(self):
        return f"<GameTransaction {self.reference_id}: {self.amount} {self.currency} ({self.action})>"