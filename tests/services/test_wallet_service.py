"""
지갑 서비스 테스트
"""
import pytest
from uuid import UUID, uuid4
from decimal import Decimal
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

from backend.services.wallet.wallet_service import WalletService
from backend.models.domain.wallet import Wallet, Transaction, TransactionType, TransactionStatus
from backend.schemas.wallet import DebitRequest, CreditRequest, RollbackRequest
from backend.core.exceptions import (
    InsufficientFundsError, DuplicateTransactionError, 
    WalletNotFoundError, CurrencyMismatchError
)

# 테스트 데이터
@pytest.fixture
def wallet_data():
    """테스트용 지갑 데이터"""
    return {
        "id": uuid4(),
        "player_id": uuid4(),
        "partner_id": uuid4(),
        "balance": Decimal("1000.00"),
        "currency": "USD",
        "is_active": True,
        "is_locked": False,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

@pytest.fixture
def transaction_data():
    """테스트용 트랜잭션 데이터"""
    return {
        "id": uuid4(),
        "reference_id": "TEST-TX-123",
        "wallet_id": uuid4(),
        "player_id": uuid4(),
        "partner_id": uuid4(),
        "transaction_type": TransactionType.BET,
        "amount": Decimal("100.00"),
        "currency": "USD",
        "status": TransactionStatus.COMPLETED,
        "original_balance": Decimal("1000.00"),
        "updated_balance": Decimal("900.00"),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

@pytest.fixture
def db_session():
    """모의 DB 세션"""
    session = AsyncMock()
    session.flush = AsyncMock()
    return session

@pytest.fixture
def wallet_service(db_session):
    """지갑 서비스 인스턴스"""
    service = WalletService(db_session)
    
    # 리포지토리 모의 객체 생성
    service.wallet_repo = AsyncMock()
    service.partner_repo = AsyncMock()
    
    # Redis 모의 객체 생성
    service.redis = AsyncMock()
    service.redis.get = AsyncMock(return_value=None)
    service.redis.set = AsyncMock(return_value=True)
    service.redis.delete = AsyncMock(return_value=True)
    
    # 이벤트 발행 모의 객체 생성
    service._publish_transaction_event = AsyncMock()
    
    return service

@pytest.mark.asyncio
async def test_get_wallet(wallet_service, wallet_data):
    """지갑 조회 테스트"""
    # 모의 리포지토리 설정
    wallet = Wallet(**wallet_data)
    wallet_service.wallet_repo.get_player_wallet.return_value = wallet
    
    # 함수 호출
    result = await wallet_service.get_wallet(wallet_data["player_id"], wallet_data["partner_id"])
    
    # 검증
    assert result == wallet
    wallet_service.wallet_repo.get_player_wallet.assert_called_with(
        wallet_data["player_id"], wallet_data["partner_id"]
    )
    wallet_service.redis.get.assert_called_once()

@pytest.mark.asyncio
async def test_create_wallet(wallet_service, wallet_data):
    """지갑 생성 테스트"""
    # 모의 리포지토리 설정
    wallet = Wallet(**wallet_data)
    wallet_service.wallet_repo.create_wallet.return_value = wallet
    
    # 파트너 모의 설정
    partner = MagicMock()
    partner.id = wallet_data["partner_id"]
    wallet_service.partner_repo.get_partner_by_id.return_value = partner
    
    # 함수 호출
    result = await wallet_service.create_wallet(
        wallet_data["player_id"], wallet_data["partner_id"], wallet_data["currency"]
    )
    
    # 검증
    assert result == wallet
    wallet_service.partner_repo.get_partner_by_id.assert_called_with(wallet_data["partner_id"])
    wallet_service.wallet_repo.create_wallet.assert_called_once()
    wallet_service.redis.delete.assert_called_once()

@pytest.mark.asyncio
async def test_debit_success(wallet_service, wallet_data):
    """자금 차감 성공 테스트"""
    # 모의 지갑 설정
    wallet = Wallet(**wallet_data)
    wallet_service.wallet_repo.get_player_wallet.return_value = wallet
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None
    
    # 차감 요청 생성
    request = DebitRequest(
        player_id=wallet_data["player_id"],
        reference_id="TEST-DEBIT-123",
        amount=Decimal("100.00"),
        currency=wallet_data["currency"]
    )
    
    # 함수 호출
    result = await wallet_service.debit(request, wallet_data["partner_id"])
    
    # 검증
    assert result.status == "OK"
    assert result.balance == Decimal("900.00")
    assert result.currency == wallet_data["currency"]
    assert result.player_id == wallet_data["player_id"]
    assert wallet.balance == Decimal("900.00")  # 잔액 차감 확인
    
    wallet_service.wallet_repo.create_transaction.assert_called_once()
    wallet_service.redis.delete.assert_called_once()
    wallet_service._publish_transaction_event.assert_called_once()

@pytest.mark.asyncio
async def test_debit_insufficient_funds(wallet_service, wallet_data):
    """자금 부족 테스트"""
    # 모의 지갑 설정 (낮은 잔액)
    wallet_data["balance"] = Decimal("50.00")
    wallet = Wallet(**wallet_data)
    wallet_service.wallet_repo.get_player_wallet.return_value = wallet
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None
    
    # 차감 요청 생성 (잔액보다 큰 금액)
    request = DebitRequest(
        player_id=wallet_data["player_id"],
        reference_id="TEST-DEBIT-124",
        amount=Decimal("100.00"),
        currency=wallet_data["currency"]
    )
    
    # 예외 발생 확인
    with pytest.raises(InsufficientFundsError):
        await wallet_service.debit(request, wallet_data["partner_id"])
    
    # 잔액이 변경되지 않았는지 확인
    assert wallet.balance == Decimal("50.00")
    wallet_service.wallet_repo.create_transaction.assert_not_called()

@pytest.mark.asyncio
async def test_credit_success(wallet_service, wallet_data):
    """자금 추가 성공 테스트"""
    # 모의 지갑 설정
    wallet = Wallet(**wallet_data)
    wallet_service.ensure_wallet_exists = AsyncMock(return_value=(wallet, False))
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None
    
    # 추가 요청 생성
    request = CreditRequest(
        player_id=wallet_data["player_id"],
        reference_id="TEST-CREDIT-123",
        amount=Decimal("200.00"),
        currency=wallet_data["currency"]
    )
    
    # 함수 호출
    result = await wallet_service.credit(request, wallet_data["partner_id"])
    
    # 검증
    assert result.status == "OK"
    assert result.balance == Decimal("1200.00")
    assert result.currency == wallet_data["currency"]
    assert result.player_id == wallet_data["player_id"]
    assert wallet.balance == Decimal("1200.00")  # 잔액 증가 확인
    
    wallet_service.wallet_repo.create_transaction.assert_called_once()
    wallet_service.redis.delete.assert_called_once()
    wallet_service._publish_transaction_event.assert_called_once()

@pytest.mark.asyncio
async def test_credit_duplicate_transaction(wallet_service, transaction_data):
    """중복 입금 처리 테스트 (멱등성)"""
    # 모의 설정: 이미 존재하는 트랜잭션
    transaction_data["transaction_type"] = TransactionType.WIN
    transaction = Transaction(**transaction_data)
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = transaction
    
    # 지갑 모의 설정
    wallet = Wallet(
        id=transaction_data["wallet_id"],
        player_id=transaction_data["player_id"],
        partner_id=transaction_data["partner_id"],
        balance=transaction_data["updated_balance"],
        currency=transaction_data["currency"],
        is_active=True
    )
    wallet_service.get_wallet = AsyncMock(return_value=wallet)
    
    # 동일 참조 ID로 요청
    request = CreditRequest(
        player_id=transaction_data["player_id"],
        reference_id=transaction_data["reference_id"],
        amount=Decimal("200.00"),  # 다른 금액 (무시됨)
        currency=transaction_data["currency"]
    )
    
    # 함수 호출
    result = await wallet_service.credit(request, transaction_data["partner_id"])
    
    # 검증: 원래 트랜잭션 정보가 반환됨 (멱등성)
    assert result.reference_id == transaction_data["reference_id"]
    assert result.amount == transaction_data["amount"]
    assert result.balance == transaction_data["updated_balance"]
    
    # 새로운 트랜잭션이 생성되지 않음
    wallet_service.wallet_repo.create_transaction.assert_not_called()

@pytest.mark.asyncio
async def test_rollback_success(wallet_service, transaction_data, wallet_data):
    """트랜잭션 롤백 성공 테스트"""
    # 원본 트랜잭션 모의 설정 (베팅)
    transaction_data["transaction_type"] = TransactionType.BET
    original_tx = Transaction(**transaction_data)
    wallet_service.wallet_repo.get_transaction_by_reference.side_effect = [
        None,  # 롤백 트랜잭션 중복 확인
        original_tx  # 원본 트랜잭션 조회
    ]
    
    # 지갑 모의 설정
    wallet = Wallet(**wallet_data)
    wallet.id = transaction_data["wallet_id"]
    wallet_service.wallet_repo.get_player_wallet.return_value = wallet
    
    # 롤백 요청 생성
    request = RollbackRequest(
        player_id=transaction_data["player_id"],
        reference_id="TEST-ROLLBACK-123",
        original_reference_id=transaction_data["reference_id"]
    )
    
    # 함수 호출
    result = await wallet_service.rollback(request, transaction_data["partner_id"])
    
    # 검증
    assert result.status == "OK"
    assert result.balance == Decimal("1100.00")  # 베팅 금액이 복구됨
    assert result.reference_id == "TEST-ROLLBACK-123"
    assert result.player_id == transaction_data["player_id"]
    assert original_tx.status == TransactionStatus.CANCELED  # 원본 트랜잭션 상태 변경 확인
    
    wallet_service.wallet_repo.create_transaction.assert_called_once()
    wallet_service.redis.delete.assert_called_once()
    wallet_service._publish_transaction_event.assert_called_once()