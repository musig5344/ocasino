"""
지갑 관련 도메인 모델
"""
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, Dict, Any
from decimal import Decimal
from enum import Enum

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Numeric, JSON, Index
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID
from sqlalchemy.orm import relationship

from backend.db.database import Base

class TransactionType(str, Enum):
    """트랜잭션 유형"""
    DEPOSIT = "deposit"          # 입금
    WITHDRAWAL = "withdrawal"    # 출금
    BET = "bet"                  # 베팅
    WIN = "win"                  # 승리
    REFUND = "refund"            # 환불
    ADJUSTMENT = "adjustment"    # 수동 조정
    COMMISSION = "commission"    # 수수료
    BONUS = "bonus"              # 보너스

class TransactionStatus(str, Enum):
    """트랜잭션 상태"""
    PENDING = "pending"          # 처리 중
    COMPLETED = "completed"      # 완료
    FAILED = "failed"            # 실패
    CANCELED = "canceled"        # 취소됨

class Wallet(Base):
    """지갑 모델"""
    __tablename__ = "wallets"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    player_id = Column(PSQL_UUID(as_uuid=True), nullable=False, index=True)
    partner_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("partners.id"), nullable=False)
    
    balance = Column(Numeric(precision=18, scale=2), nullable=False, default=0)
    currency = Column(String(3), nullable=False)
    
    is_active = Column(Boolean, default=True)
    is_locked = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    partner = relationship("Partner", back_populates="wallets")
    transactions = relationship("Transaction", back_populates="wallet")
    
    # 복합 인덱스: player_id + partner_id
    __table_args__ = (
        Index('ix_wallet_player_partner', 'player_id', 'partner_id', unique=True),
    )
    
    def __repr__(self):
        return f"<Wallet {self.id}: {self.balance} {self.currency}>"

class Transaction(Base):
    """트랜잭션 모델"""
    __tablename__ = "transactions"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    reference_id = Column(String(100), unique=True, nullable=False, index=True)
    wallet_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("wallets.id"), nullable=False)
    player_id = Column(PSQL_UUID(as_uuid=True), nullable=False, index=True)
    partner_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("partners.id"), nullable=False)
    
    transaction_type = Column(SQLEnum(TransactionType), nullable=False)
    amount = Column(Numeric(precision=18, scale=2), nullable=False)
    currency = Column(String(3), nullable=False)
    
    status = Column(SQLEnum(TransactionStatus), nullable=False, default=TransactionStatus.PENDING)
    original_balance = Column(Numeric(precision=18, scale=2), nullable=False)
    updated_balance = Column(Numeric(precision=18, scale=2), nullable=False)
    
    game_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("games.id"))
    game_session_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("game_sessions.id"))
    
    reference_transaction_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("transactions.id"))
    metadata = Column(JSON)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    wallet = relationship("Wallet", back_populates="transactions")
    
    def __repr__(self):
        return f"<Transaction {self.reference_id}: {self.amount} {self.currency} ({self.transaction_type})>"

class Balance(Base):
    """잔액 현황 모델 (파트너별 통화별 합계)"""
    __tablename__ = "balances"
    
    id = Column(PSQL_UUID(as_uuid=True), primary_key=True, default=uuid4)
    partner_id = Column(PSQL_UUID(as_uuid=True), ForeignKey("partners.id"), nullable=False)
    currency = Column(String(3), nullable=False)
    
    total_balance = Column(Numeric(precision=18, scale=2), nullable=False, default=0)
    available_balance = Column(Numeric(precision=18, scale=2), nullable=False, default=0)
    pending_withdrawals = Column(Numeric(precision=18, scale=2), nullable=False, default=0)
    
    last_updated_at = Column(DateTime, default=datetime.utcnow)
    
    # 복합 인덱스: partner_id + currency
    __table_args__ = (
        Index('ix_balance_partner_currency', 'partner_id', 'currency', unique=True),
    )
    
    def __repr__(self):
        return f"<Balance {self.partner_id}: {self.total_balance} {self.currency}>"