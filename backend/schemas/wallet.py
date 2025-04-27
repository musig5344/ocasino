from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from decimal import Decimal
from typing import Optional, List, Dict, Any
from datetime import datetime
from backend.models.domain.wallet import TransactionType, TransactionStatus # Enum 임포트


# --- Wallet Schemas ---

class WalletBase(BaseModel):
    """ 지갑 기본 스키마 """
    player_id: UUID
    partner_id: UUID
    currency: str = Field(..., min_length=3, max_length=3) # ISO 4217

class WalletCreate(WalletBase):
    """ 지갑 생성 요청 스키마 """
    pass # WalletBase 와 동일, 필요시 필드 추가

class WalletUpdate(BaseModel):
    """ 지갑 업데이트 요청 스키마 (예: 활성/잠금 상태 변경) """
    is_active: Optional[bool] = None
    is_locked: Optional[bool] = None

class Wallet(WalletBase):
    """ 지갑 응답 스키마 (DB 모델 기반) """
    id: UUID
    balance: Decimal
    is_active: bool
    is_locked: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# --- Transaction Schemas ---

class TransactionBase(BaseModel):
    """ 거래 기본 스키마 """
    player_id: UUID
    reference_id: str = Field(..., max_length=255) # 고유 참조 ID (파트너사 제공)
    currency: str = Field(..., min_length=3, max_length=3)
    amount: Decimal = Field(..., gt=0) # 항상 양수여야 함

class DebitRequest(TransactionBase):
    """ 차감 (Debit/Bet) 요청 스키마 """
    transaction_type: Optional[TransactionType] = Field(None, description="트랜잭션 유형 (지정하지 않으면 BET으로 간주)")
    game_id: Optional[UUID] = Field(None, description="관련 게임 ID")
    game_session_id: Optional[UUID] = Field(None, description="게임 세션 ID")
    round_id: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    # 추가 메타데이터 (필요시)
    metadata: Optional[Dict[str, Any]] = None

class CreditRequest(TransactionBase):
    """ 적립 (Credit/Win) 요청 스키마 """
    transaction_type: Optional[TransactionType] = Field(None, description="트랜잭션 유형 (지정하지 않으면 WIN으로 간주)")
    related_bet_reference_id: Optional[str] = Field(None, max_length=255)
    game_id: Optional[UUID] = Field(None, description="관련 게임 ID")
    game_session_id: Optional[UUID] = Field(None, description="게임 세션 ID")
    round_id: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    # 추가 메타데이터
    metadata: Optional[Dict[str, Any]] = None

class TransactionRequest(BaseModel):
    """ 일반 거래 요청 스키마 (Deposit, Withdraw, Bet, Win, Cancel 등 다양한 핸들러에서 사용) """
    reference_id: str = Field(..., max_length=255, description="파트너사 제공 고유 트랜잭션 ID")
    amount: Decimal = Field(..., gt=0, description="거래 금액")
    currency: str = Field(..., min_length=3, max_length=3, description="통화 코드 (ISO 4217)")
    game_id: Optional[UUID] = Field(None, description="관련 게임 ID (Bet/Win/Cancel 시)")
    ref_transaction_id: Optional[str] = Field(None, max_length=255, description="참조(원본) 트랜잭션 ID (Cancel/Rollback 시)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="추가 메타데이터")

class RollbackRequest(BaseModel):
    """ 롤백 요청 스키마 """
    player_id: UUID  # 필수 필드로 설정
    reference_id: str = Field(..., max_length=255, description="롤백 트랜잭션의 고유 참조 ID")
    original_reference_id: str = Field(..., max_length=255, description="롤백할 원본 트랜잭션의 참조 ID")
    rollback_reason: Optional[str] = Field(None, max_length=500)
    metadata: Optional[Dict[str, Any]] = Field(None, description="추가 메타데이터")

    # Pydantic V2 호환성 및 ORM 모드 설정
    model_config = ConfigDict(
        from_attributes=True, # orm_mode = True 대체
        json_schema_extra={
            "example": {
                "player_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
                "reference_id": "ROLLBACK-UNIQUE-ID-123",
                "original_reference_id": "BET-ORIGINAL-ID-456"
            }
        }
    )

class TransactionResponse(BaseModel):
    """ 거래 응답 스키마 """
    player_id: UUID
    reference_id: str
    transaction_type: TransactionType
    amount: Decimal
    currency: str
    status: TransactionStatus
    balance: Decimal # 거래 후 잔액
    timestamp: datetime # 거래 시간 (생성 시간)
    # id: Optional[UUID] = None # 필요에 따라 내부 ID 포함

    model_config = ConfigDict(from_attributes=True)

class Transaction(TransactionBase):
    """ 거래 상세 정보 스키마 (DB 모델 기반) """
    id: UUID
    transaction_type: TransactionType
    status: TransactionStatus
    wallet_id: UUID
    partner_id: UUID # 조회 편의를 위해 추가
    game_id: Optional[str] = None
    round_id: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    original_transaction_id: Optional[UUID] = None # 롤백의 경우 원본 거래 ID
    initial_balance: Decimal # 거래 전 잔액
    updated_balance: Decimal # 거래 후 잔액

    model_config = ConfigDict(from_attributes=True)

# --- Other Schemas ---

class BalanceResponse(BaseModel):
    """ 잔액 조회 응답 스키마 """
    status: str = Field("OK", description="처리 상태")
    player_id: UUID
    partner_id: UUID
    balance: Decimal
    currency: str
    timestamp: datetime

class TransactionList(BaseModel):
    """ 거래 내역 목록 응답 스키마 """
    items: List[TransactionResponse] # 거래 응답 스키마 리스트
    total: int
    page: int
    page_size: int

class WalletActionResponse(BaseModel):
    """ 지갑 액션 응답 스키마 (Deposit, Withdraw, Win, Cancel 등) """
    status: str = Field("OK", description="처리 상태") # 상태 필드 추가 (예시)
    player_id: UUID
    partner_id: UUID
    balance: Decimal # 액션 후 잔액
    currency: str
    transaction_id: str # 해당 액션의 트랜잭션 ID (또는 reference_id)
    amount: Decimal # 처리된 금액
    type: TransactionType # 처리된 트랜잭션 유형
    timestamp: Optional[datetime] = None # 처리 시간 (선택 사항)

class PlayerWalletResponse(BaseModel):
    """ 플레이어 지갑 정보 응답 스키마 (간략화된 정보) """
    player_id: UUID
    partner_id: UUID
    currency: str
    balance: Decimal
    is_active: bool
    is_locked: bool
    last_updated: datetime

class WalletInfoResponse(BaseModel):
    player_id: UUID

# 필요에 따라 추가적인 스키마 정의 (예: 특정 조회 필터링 스키마) 