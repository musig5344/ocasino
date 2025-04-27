"""
플레이어 관련 도메인 모델
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID
from sqlalchemy.orm import relationship

from backend.db.database import Base
from backend.db.types import GUID

class Player(Base):
    """플레이어 모델"""
    __tablename__ = "players"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    partner_id = Column(GUID, ForeignKey("partners.id"), nullable=False, index=True) # 플레이어는 특정 파트너사에 속함
    username = Column(String(100), unique=True, nullable=False, index=True) # 파트너사 내에서 고유한 플레이어 ID (예: 'user123@partner_code')
    
    # 플레이어 관련 추가 정보 (필요에 따라 확장)
    # email = Column(String(255), unique=True, nullable=True, index=True)
    # first_name = Column(String(100))
    # last_name = Column(String(100))
    # phone_number = Column(String(50))
    
    is_active = Column(Boolean, default=True) # 플레이어 계정 활성 상태
    status = Column(String(50)) # 플레이어 상태 (예: 'verified', 'pending', 'suspended')

    last_login_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships (Wallet, Game Sessions 등 필요 시 추가)
    # wallet = relationship("Wallet", back_populates="player", uselist=False) 
    # game_sessions = relationship("GameSession", back_populates="player")
    partner = relationship("Partner") # players 테이블에서 partners 테이블 참조

    # 복합 고유 제약 조건: 파트너 ID + 사용자 이름
    __table_args__ = (
        UniqueConstraint('partner_id', 'username', name='uq_partner_player_username'),
    )

    def __repr__(self):
        return f"<Player id={self.id} username={self.username} partner_id={self.partner_id}>" 