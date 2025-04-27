"""
지갑 관련 API 스키마
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, Field, validator, root_validator

from backend.models.domain.wallet import TransactionType, TransactionStatus

class WalletBase(BaseModel):
    """지갑 기본 스키마"""
    player_id: UUID
    currency: str = Field(..., min_length=3, max_length=3)

class WalletCreate(WalletBase):
    """지갑 생성 스키마"""
    pass

class Wallet(WalletBase):
    """지갑 응답 스키마"""
    id: UUID
    partner_id: UUID
    balance: Decimal = Field(..., ge=0)
    is_active: bool
    is_locked: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

class TransactionBase(BaseModel):
    """트랜잭션 기본 스키마"""
    player_id: UUID
    reference_id: str = Field(..., min_length=1, max_length=100)
    transaction_type: TransactionType
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    
    # 선택적 필드
    game_id: Optional[UUID] = None
    game_session_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = None

class TransactionCreate(TransactionBase):
    """트랜잭션 생성 스키마"""
    reference_transaction_id: Optional[UUID] = None
    
    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('금액은 0보다 커야 합니다')
        return v

class Transaction(TransactionBase):
    """트랜잭션 응답 스키마"""
    id: UUID
    wallet_id: UUID
    partner_id: UUID
    status: TransactionStatus
    original_balance: Decimal
    updated_balance: Decimal
    reference_transaction_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        orm_mode = True

class WalletActionRequest(BaseModel):
    """지갑 액션 요청 기본 스키마"""
    player_id: UUID
    reference_id: str = Field(..., min_length=1, max_length=100)
    
    class Config:
        schema_extra = {
            "example": {
                "player_id": "123e4567-e89b-12d3-a456-426614174000",
                "reference_id": "TX123456789"
            }
        }

class BalanceRequest(WalletActionRequest):
    """잔액 조회 요청 스키마"""
    pass

class BalanceResponse(BaseModel):
    """잔액 조회 응답 스키마"""
    player_id: UUID
    balance: Decimal
    currency: str
    reference_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        schema_extra = {
            "example": {
                "player_id": "123e4567-e89b-12d3-a456-426614174000",
                "balance": 1000.00,
                "currency": "USD",
                "reference_id": "TX123456789",
                "timestamp": "2023-03-01T12:00:00Z"
            }
        }

class DebitRequest(WalletActionRequest):
    """출금 요청 스키마"""
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    game_id: Optional[UUID] = None
    game_session_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = None
    
    class Config:
        schema_extra = {
            "example": {
                "player_id": "123e4567-e89b-12d3-a456-426614174000",
                "reference_id": "BET123456789",
                "amount": 10.00,
                "currency": "USD",
                "game_id": "123e4567-e89b-12d3-a456-426614174000",
                "metadata": {
                    "round_id": "ROUND123",
                    "bet_type": "line_bet"
                }
            }
        }

class CreditRequest(WalletActionRequest):
    """입금 요청 스키마"""
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)
    game_id: Optional[UUID] = None
    game_session_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = None
    
    class Config:
        schema_extra = {
            "example": {
                "player_id": "123e4567-e89b-12d3-a456-426614174000",
                "reference_id": "WIN123456789",
                "amount": 20.00,
                "currency": "USD",
                "game_id": "123e4567-e89b-12d3-a456-426614174000",
                "metadata": {
                    "round_id": "ROUND123",
                    "win_type": "base_game"
                }
            }
        }

class RollbackRequest(WalletActionRequest):
    """롤백 요청 스키마"""
    original_reference_id: str = Field(..., min_length=1, max_length=100)
    
    class Config:
        schema_extra = {
            "example": {
                "player_id": "123e4567-e89b-12d3-a456-426614174000",
                "reference_id": "ROLLBACK123456789",
                "original_reference_id": "BET123456789"
            }
        }

class TransactionResponse(BaseModel):
    """트랜잭션 응답 스키마"""
    player_id: UUID
    reference_id: str
    transaction_type: TransactionType
    amount: Decimal
    currency: str
    status: TransactionStatus
    balance: Decimal
    timestamp: datetime
    transaction_id: UUID = Field(..., description="생성된 트랜잭션의 고유 ID")
    
    class Config:
        orm_mode = True
        schema_extra = {
            "example": {
                "player_id": "123e4567-e89b-12d3-a456-426614174000",
                "reference_id": "BET-123456789",
                "transaction_type": "bet",
                "amount": 10.00,
                "currency": "USD",
                "status": "completed",
                "balance": 990.00,
                "timestamp": "2023-08-15T12:34:56.789Z",
                "transaction_id": "a1b2c3d4-e89b-12d3-a456-426614174000"
            }
        }

class TransactionList(BaseModel):
    """트랜잭션 목록 응답 스키마"""
    items: List[TransactionResponse]
    total: int
    page: int
    size: int
    
    class Config:
        schema_extra = {
            "example": {
                "items": [
                    {
                        "player_id": "123e4567-e89b-12d3-a456-426614174000",
                        "reference_id": "WIN-987654321",
                        "transaction_type": "win",
                        "amount": 25.50,
                        "currency": "USD",
                        "status": "completed",
                        "balance": 1015.50,
                        "timestamp": "2023-08-15T13:00:00.123Z",
                        "transaction_id": "b2c3d4e5-e89b-12d3-a456-426614174000"
                    },
                    {
                        "player_id": "123e4567-e89b-12d3-a456-426614174000",
                        "reference_id": "BET-123456789",
                        "transaction_type": "bet",
                        "amount": 10.00,
                        "currency": "USD",
                        "status": "completed",
                        "balance": 990.00,
                        "timestamp": "2023-08-15T12:34:56.789Z",
                        "transaction_id": "a1b2c3d4-e89b-12d3-a456-426614174000"
                    }
                ],
                "total": 2,
                "page": 1,
                "size": 20
            }
        }

class WalletActionResponse(BaseModel):
    """지갑 액션 응답 스키마 (TransactionResponse 사용 권장)"""
    status: str = Field("OK", description="트랜잭션 상태")
    balance: Decimal = Field(..., description="업데이트된 잔액")
    currency: str = Field(..., description="통화 코드", min_length=3, max_length=3)
    transaction_id: str = Field(..., description="트랜잭션 ID")
    player_id: UUID = Field(..., description="플레이어 ID")
    reference_id: str = Field(..., description="참조 ID")
    amount: Decimal = Field(..., description="트랜잭션 금액")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="트랜잭션 시간")
    
    class Config:
        schema_extra = {
            "example": {
                "status": "OK",
                "balance": 990.00,
                "currency": "USD",
                "transaction_id": "TX-123456789",
                "player_id": "123e4567-e89b-12d3-a456-426614174000",
                "reference_id": "BET-123456789",
                "amount": 10.00,
                "timestamp": "2023-08-15T12:34:56.789Z"
            }
        }