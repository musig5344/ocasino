"""
지갑 관련 도메인 모델
"""
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, Dict, Any
from decimal import Decimal
from enum import Enum
import logging

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Numeric, JSON, Index, Text, BigInteger, LargeBinary
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property

from backend.db.database import Base
from backend.db.types import UUIDType, GUID
from backend.utils import encryption
from backend.utils.encryption import decrypt_aes_gcm
from backend.core.exceptions import InvalidAmountError, CurrencyMismatchError

logger = logging.getLogger(__name__)

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
    ROLLBACK = "rollback"        # 트랜잭션 롤백 (이전 거래 취소)

class TransactionStatus(str, Enum):
    """트랜잭션 상태"""
    PENDING = "pending"          # 처리 중
    COMPLETED = "completed"      # 완료
    FAILED = "failed"            # 실패
    CANCELED = "canceled"        # 취소됨

class Wallet(Base):
    """지갑 모델"""
    __tablename__ = "wallets"
    
    id = Column(GUID, primary_key=True, default=uuid4)
    player_id = Column(GUID, nullable=False, index=True)
    partner_id = Column(GUID, ForeignKey("partners.id"), nullable=False, index=True)
    
    balance = Column(Numeric(precision=18, scale=2), nullable=False, default=0)
    currency = Column(String(3), nullable=False)
    
    is_active = Column(Boolean, default=True)
    is_locked = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    partner = relationship("Partner", back_populates="wallets")
    transactions = relationship("Transaction", back_populates="wallet", cascade="all, delete-orphan")
    
    # 복합 인덱스: player_id + partner_id
    __table_args__ = (
        Index('ix_wallet_player_partner', 'player_id', 'partner_id', unique=True),
    )
    
    def __repr__(self):
        return f"<Wallet {self.id}: {self.balance} {self.currency}>"

class Transaction(Base):
    """트랜잭션 모델"""
    __tablename__ = "transactions"
    
    id = Column(GUID, primary_key=True, default=uuid4)
    reference_id = Column(String(100), nullable=False)
    wallet_id = Column(GUID, ForeignKey("wallets.id"), nullable=False)
    player_id = Column(GUID, nullable=False, index=True)
    partner_id = Column(GUID, ForeignKey("partners.id"), nullable=False)
    
    transaction_type = Column(SQLEnum(TransactionType), nullable=False)
    
    # 암호화된 금액을 저장할 컬럼 (타입: Text 또는 String)
    # Numeric 대신 문자열 형태로 저장 (Base64 인코딩된 결과)
    # 컬럼명 앞에 _ 를 붙여 내부 사용임을 표시
    _encrypted_amount = Column("amount", Text, nullable=False)
    
    currency = Column(String(3), nullable=False)
    
    status = Column(SQLEnum(TransactionStatus), nullable=False, default=TransactionStatus.PENDING)
    
    # 잔액 필드도 암호화 고려 대상이지만, 성능 및 쿼리 제약으로 인해
    # 여기서는 일단 amount만 암호화하는 것으로 진행합니다.
    # 만약 original/updated balance도 암호화한다면 동일한 패턴을 적용해야 합니다.
    original_balance = Column(Numeric(precision=18, scale=2), nullable=False)
    updated_balance = Column(Numeric(precision=18, scale=2), nullable=False)
    
    game_id = Column(GUID, ForeignKey("games.id"), nullable=True)
    game_session_id = Column(GUID, ForeignKey("game_sessions.id"), nullable=True)
    
    original_transaction_id = Column(GUID, ForeignKey("transactions.id"), nullable=True)
    original_transaction = relationship(
        "Transaction", 
        remote_side=[id], 
        backref="refund_transactions",
        foreign_keys=[original_transaction_id]
    )
    
    # metadata 필드 암호화: 필드 전체를 암호화하거나, 내부의 특정 민감 정보만
    # 선별적으로 암호화/마스킹하는 방법 고려 가능.
    # SQLAlchemy 이벤트 리스너(before_insert, before_update)를 사용하여 처리하거나,
    # 서비스 레이어에서 저장 전에 처리하는 것이 적합할 수 있음.
    transaction_metadata = Column("metadata", JSON)
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    wallet = relationship("Wallet", back_populates="transactions")
    
    # 복합 고유 제약조건 추가
    __table_args__ = (
        Index('ix_transactions_wallet_id', 'wallet_id'),
        Index('uq_transaction_partner_reference', 'partner_id', 'reference_id', unique=True),
        Index('ix_transactions_reference_id', 'reference_id')
    )
    
    @hybrid_property
    def amount(self) -> Decimal:
        """암호화된 금액을 복호화하여 Decimal 타입으로 반환합니다."""
        try:
            decrypted_value = decrypt_aes_gcm(self._encrypted_amount)
            if decrypted_value is None:
                # 복호화 실패 시 또는 DB 값이 NULL인 경우
                logger.error(f"Failed to decrypt amount for transaction {self.id}. Returning 0.")
                return Decimal('0.00')
            return Decimal(decrypted_value)
        except Exception as e:
            # 예상치 못한 오류 발생 시 (예: Decimal 변환 실패)
            logger.exception(f"Error decrypting or converting amount for transaction {self.id}: {e}")
            return Decimal('0.00') # 안전한 기본값 반환

    @amount.setter
    def amount(self, value: Any):
        """입력된 값을 암호화하여 _encrypted_amount 컬럼에 저장합니다."""
        if value is None:
            # None 값을 어떻게 처리할지 정책 결정 필요
            # 여기서는 암호화하지 않고 None 저장 시도 (DB 제약조건에 따라 실패 가능)
            # 또는 에러 발생시키거나, '0'을 암호화할 수 있음
            # self._encrypted_amount = None
            # 여기서는 ValueError 발생시킴
            raise ValueError("Amount cannot be None")

        # 입력값을 문자열로 변환하여 암호화
        try:
            # Decimal 타입 등이 입력될 수 있으므로 str()로 변환
            plaintext = str(value)
            # 모듈 경로를 명시적으로 사용하여 호출
            self._encrypted_amount = encryption.encrypt_aes_gcm(plaintext)
        except Exception as e:
            # 암호화 실패 처리
            logger.exception(f"Error encrypting amount for transaction: {e}")
            # 암호화 실패 시 저장 로직 중단 또는 기본값 설정 등 처리 필요
            # 여기서는 예외를 다시 발생시켜 저장 실패를 알림
            raise ValueError(f"Failed to encrypt amount: {e}") from e

    # DB 수준에서의 amount 필터링/정렬은 불가능해집니다.
    # 만약 특정 암호화된 값과 일치하는지 확인하는 쿼리가 필요하다면,
    # @amount.expression 데코레이터를 사용하여 특정 값을 암호화한 결과와 비교할 수 있습니다.
    # 예: @amount.expression
    #     def amount(cls):
    #         # 이 함수는 SQLAlchemy 쿼리 컨텍스트에서 호출됩니다.
    #         # 실제 값 비교는 어렵고, 특정 암호화된 문자열과의 일치 여부만 확인 가능
    #         # return cls._encrypted_amount # 이렇게만 하면 암호화된 값 자체로 쿼리됨
    #         # 특정 값을 암호화해서 비교해야 함:
    #         # target_value_encrypted = encrypt_aes_gcm(str(target_value))
    #         # return cls._encrypted_amount == target_value_encrypted
    #         # 하지만 이는 매우 제한적입니다.
    #         pass # DB 레벨 쿼리 표현식은 기본적으로 비활성화

    def __repr__(self):
        # repr에서도 복호화된 amount 사용 (성능 영향 주의)
        try:
            amount_repr = str(self.amount) # amount getter 호출
        except Exception:
            amount_repr = "[decryption error]"
        return f"<Transaction {self.reference_id}: {amount_repr} {self.currency} ({self.transaction_type})>"

class Balance(Base):
    """잔액 현황 모델 (파트너별 통화별 합계)"""
    __tablename__ = "balances"
    
    id = Column(UUIDType, primary_key=True, default=uuid4)
    partner_id = Column(UUIDType, ForeignKey("partners.id"), nullable=False)
    currency = Column(String(3), nullable=False)
    
    total_balance = Column(Numeric(precision=18, scale=2), nullable=False, default=0)
    available_balance = Column(Numeric(precision=18, scale=2), nullable=False, default=0)
    pending_withdrawals = Column(Numeric(precision=18, scale=2), nullable=False, default=0)
    
    last_updated_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    # 복합 인덱스: partner_id + currency
    __table_args__ = (
        Index('ix_balance_partner_currency', 'partner_id', 'currency', unique=True),
    )
    
    def __repr__(self):
        return f"<Balance {self.partner_id}: {self.total_balance} {self.currency}>"