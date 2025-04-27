import pytest
from unittest.mock import AsyncMock, patch
from decimal import Decimal

# 필요한 예외 클래스 정의
class InvalidAmountError(Exception):
    pass

class InsufficientFundsError(Exception):
    pass

class UserNotFoundError(Exception):
    pass

class WalletOperationError(Exception):
    pass

# 분리된 withdraw_funds 함수 정의
async def withdraw_funds(player_id: str, amount: Decimal, currency: str, wallet_repo, cache_service=None):
    """
    사용자 지갑에서 금액을 출금하는 함수
    
    Args:
        player_id (str): 사용자 ID
        amount (Decimal): 출금 금액
        currency (str): 통화 단위
        wallet_repo: 지갑 저장소 객체
        cache_service: 캐시 서비스 객체 (기본값: None)
        
    Returns:
        dict: 업데이트된 잔액 정보
        
    Raises:
        InvalidAmountError: 출금 금액이 유효하지 않은 경우
        InsufficientFundsError: 잔액이 부족한 경우
        UserNotFoundError: 사용자를 찾을 수 없는 경우
        WalletOperationError: 지갑 작업 중 오류 발생
    """
    # 출금 금액 유효성 검사
    if amount <= Decimal("0"):
        raise InvalidAmountError("출금 금액은 0보다 커야 합니다")
    
    # 기존 잔액 조회
    current_balance = await wallet_repo.get_balance_by_player_id(player_id, currency)
    if current_balance is None:
        raise UserNotFoundError(f"사용자 ID {player_id}를 찾을 수 없습니다")
    
    # 잔액 부족 검사
    if current_balance < amount:
        raise InsufficientFundsError(f"잔액 부족: 현재 잔액 {current_balance}, 요청 금액 {amount}")
    
    # 새 잔액 계산
    new_balance = current_balance - amount
    
    # 트랜잭션 생성
    transaction_id = await wallet_repo.create_transaction(
        player_id=player_id,
        amount=amount, # 출금은 보통 음수로 기록하지 않고 type으로 구분
        currency=currency,
        transaction_type="withdraw",
        status="completed"
    )
    
    # 잔액 업데이트
    updated_balance_data = await wallet_repo.update_balance(
        player_id=player_id,
        new_balance=new_balance,
        currency=currency,
        transaction_id=transaction_id
    )

    # 업데이트 실패 시 처리
    if updated_balance_data is None:
        raise WalletOperationError(f"Failed to update balance for player {player_id} during withdrawal")

    # 캐시 업데이트 (캐시 서비스가 있는 경우)
    if cache_service:
        try:
            await cache_service.delete(f"balance:{player_id}:{currency}")
        except Exception as e:
            print(f"Warning: Failed to delete cache for {player_id}:{currency} during withdrawal - {e}")
            pass
    
    return updated_balance_data

# 테스트 케이스
@pytest.mark.asyncio
async def test_withdraw_funds_success():
    """정상적인 출금 처리를 테스트합니다."""
    # Mock 객체 생성
    wallet_repo = AsyncMock()
    cache_service = AsyncMock()
    
    # Mock 동작 설정
    player_id = "user123"
    currency = "USD"
    current_balance = Decimal("100.00")
    withdraw_amount = Decimal("50.00")
    transaction_id = "txn_withdraw_123"
    expected_new_balance = Decimal("50.00")
    
    wallet_repo.get_balance_by_player_id.return_value = current_balance
    wallet_repo.create_transaction.return_value = transaction_id
    wallet_repo.update_balance.return_value = {
        "player_id": player_id,
        "balance": expected_new_balance,
        "currency": currency,
        "updated_at": "2023-01-01T12:00:00Z"
    }
    
    # 함수 실행
    result = await withdraw_funds(
        player_id=player_id,
        amount=withdraw_amount,
        currency=currency,
        wallet_repo=wallet_repo,
        cache_service=cache_service
    )
    
    # 검증
    wallet_repo.get_balance_by_player_id.assert_called_once_with(player_id, currency)
    wallet_repo.create_transaction.assert_called_once_with(
        player_id=player_id,
        amount=withdraw_amount,
        currency=currency,
        transaction_type="withdraw",
        status="completed"
    )
    wallet_repo.update_balance.assert_called_once_with(
        player_id=player_id,
        new_balance=expected_new_balance,
        currency=currency,
        transaction_id=transaction_id
    )
    cache_service.delete.assert_called_once_with(f"balance:{player_id}:{currency}")
    
    assert result["player_id"] == player_id
    assert isinstance(result["balance"], Decimal)
    assert result["balance"] == expected_new_balance
    assert result["currency"] == currency

@pytest.mark.asyncio
async def test_withdraw_funds_invalid_amount():
    """잘못된 출금 금액(0 또는 음수)을 테스트합니다."""
    wallet_repo = AsyncMock()
    cache_service = AsyncMock()
    
    with pytest.raises(InvalidAmountError, match="0보다 커야 합니다"):
        await withdraw_funds(
            player_id="user123",
            amount=Decimal("-10.00"),
            currency="USD",
            wallet_repo=wallet_repo,
            cache_service=cache_service
        )
    
    with pytest.raises(InvalidAmountError, match="0보다 커야 합니다"):
        await withdraw_funds(
            player_id="user123",
            amount=Decimal("0"),
            currency="USD",
            wallet_repo=wallet_repo,
            cache_service=cache_service
        )
    
    wallet_repo.get_balance_by_player_id.assert_not_called()
    wallet_repo.create_transaction.assert_not_called()
    wallet_repo.update_balance.assert_not_called()

@pytest.mark.asyncio
async def test_withdraw_funds_user_not_found():
    """존재하지 않는 사용자 테스트"""
    wallet_repo = AsyncMock()
    wallet_repo.get_balance_by_player_id.return_value = None
    player_id = "nonexistent_user"

    with pytest.raises(UserNotFoundError, match=f"사용자 ID {player_id}를 찾을 수 없습니다"):
        await withdraw_funds(
            player_id=player_id,
            amount=Decimal("50.00"),
            currency="USD",
            wallet_repo=wallet_repo
        )
    
    wallet_repo.get_balance_by_player_id.assert_called_once_with(player_id, "USD")
    wallet_repo.create_transaction.assert_not_called()
    wallet_repo.update_balance.assert_not_called()

@pytest.mark.asyncio
async def test_withdraw_funds_insufficient_balance():
    """잔액 부족 테스트"""
    wallet_repo = AsyncMock()
    player_id = "user123"
    currency = "USD"
    current_balance = Decimal("30.00")
    withdraw_amount = Decimal("50.00")
    wallet_repo.get_balance_by_player_id.return_value = current_balance
    
    with pytest.raises(InsufficientFundsError, match=f"잔액 부족: 현재 잔액 {current_balance}, 요청 금액 {withdraw_amount}"):
        await withdraw_funds(
            player_id=player_id,
            amount=withdraw_amount,
            currency=currency,
            wallet_repo=wallet_repo
        )
    
    wallet_repo.get_balance_by_player_id.assert_called_once_with(player_id, currency)
    wallet_repo.create_transaction.assert_not_called()
    wallet_repo.update_balance.assert_not_called()

@pytest.mark.asyncio
async def test_withdraw_funds_update_balance_fails():
    """잔액 업데이트 실패 테스트"""
    wallet_repo = AsyncMock()
    cache_service = AsyncMock()
    player_id = "user123"
    currency = "USD"
    current_balance = Decimal("100.00")
    withdraw_amount = Decimal("50.00")
    transaction_id = "txn_update_fail"

    wallet_repo.get_balance_by_player_id.return_value = current_balance
    wallet_repo.create_transaction.return_value = transaction_id
    # Simulate update_balance failing by returning None
    wallet_repo.update_balance.return_value = None 
    
    with pytest.raises(WalletOperationError, match=f"Failed to update balance for player {player_id} during withdrawal"):
        await withdraw_funds(
            player_id=player_id,
            amount=withdraw_amount,
            currency=currency,
            wallet_repo=wallet_repo,
            cache_service=cache_service # Include cache service if it should be called before failure
        )
    
    wallet_repo.get_balance_by_player_id.assert_called_once()
    wallet_repo.create_transaction.assert_called_once()
    wallet_repo.update_balance.assert_called_once()
    # Cache should not be deleted if update failed
    cache_service.delete.assert_not_called() 