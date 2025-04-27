import pytest
from unittest.mock import AsyncMock, patch
from decimal import Decimal

# 필요한 예외 클래스 정의
class InvalidAmountError(Exception):
    pass

class WalletOperationError(Exception):
    pass

class UserNotFoundError(Exception):
    pass

# 분리된 deposit_funds 함수 정의
async def deposit_funds(player_id: str, amount: Decimal, currency: str, wallet_repo, cache_service=None):
    """
    사용자 지갑에 금액을 입금하는 함수
    
    Args:
        player_id (str): 사용자 ID
        amount (Decimal): 입금 금액
        currency (str): 통화 단위
        wallet_repo: 지갑 저장소 객체
        cache_service: 캐시 서비스 객체 (기본값: None)
        
    Returns:
        dict: 업데이트된 잔액 정보
        
    Raises:
        InvalidAmountError: 입금 금액이 유효하지 않은 경우
        UserNotFoundError: 사용자를 찾을 수 없는 경우
        WalletOperationError: 지갑 작업 중 오류 발생
    """
    # 입금 금액 유효성 검사
    if amount <= Decimal("0"):
        raise InvalidAmountError("입금 금액은 0보다 커야 합니다")
    
    # 기존 잔액 조회
    current_balance = await wallet_repo.get_balance_by_player_id(player_id, currency)
    if current_balance is None:
        # 사용자에게 지갑이 없는 경우, 새 지갑 생성 또는 오류 처리
        # 실제 서비스에서는 여기서 지갑을 생성할 수도 있지만, 테스트 함수에서는 UserNotFoundError를 발생시킵니다.
        raise UserNotFoundError(f"사용자 ID {player_id}를 찾을 수 없습니다")
    
    # 새 잔액 계산
    new_balance = current_balance + amount
    
    # 트랜잭션 생성
    # 실제로는 DB 트랜잭션 컨텍스트 내에서 실행될 수 있음
    transaction_id = await wallet_repo.create_transaction(
        player_id=player_id,
        amount=amount,
        currency=currency,
        transaction_type="deposit",
        status="completed" # 실제로는 "pending" -> "completed"일 수 있음
    )
    
    # 잔액 업데이트
    updated_balance_data = await wallet_repo.update_balance(
        player_id=player_id,
        new_balance=new_balance,
        currency=currency,
        transaction_id=transaction_id
    )

    # update_balance가 None을 반환하면 오류 처리 (예: 업데이트 실패)
    if updated_balance_data is None:
        # 여기서는 예시로 WalletOperationError를 발생시킵니다.
        # 실제로는 트랜잭션 롤백 등이 필요할 수 있습니다.
        raise WalletOperationError(f"Failed to update balance for player {player_id}")
    
    # 캐시 업데이트 (캐시 서비스가 있는 경우)
    if cache_service:
        # 사용자의 잔액 캐시 삭제 (다음 요청 시 최신 데이터를 가져오도록)
        try:
            # 캐시 키 형식은 실제 구현과 일치해야 합니다.
            await cache_service.delete(f"balance:{player_id}:{currency}")
        except Exception as e:
            # 캐시 삭제 실패는 로깅하고 넘어갈 수 있음 (핵심 기능 아님)
            print(f"Warning: Failed to delete cache for {player_id}:{currency} - {e}") 
            pass 
    
    return updated_balance_data

# 테스트 케이스
@pytest.mark.asyncio
async def test_deposit_funds_success():
    """정상적인 입금 처리를 테스트합니다."""
    # Mock 객체 생성
    wallet_repo = AsyncMock()
    cache_service = AsyncMock()
    
    # Mock 동작 설정
    player_id = "user123"
    currency = "USD"
    current_balance = Decimal("100.00")
    deposit_amount = Decimal("50.00")
    transaction_id = "txn123456"
    expected_new_balance = Decimal("150.00")
    
    # repo.get_balance_by_player_id가 Decimal을 반환하도록 설정
    wallet_repo.get_balance_by_player_id.return_value = current_balance 
    wallet_repo.create_transaction.return_value = transaction_id
    # repo.update_balance가 업데이트된 잔액 정보를 담은 dict를 반환하도록 설정
    wallet_repo.update_balance.return_value = {
        "player_id": player_id,
        "balance": expected_new_balance, 
        "currency": currency,
        "updated_at": "2023-01-01T12:00:00Z" # 예시 시간
    }
    
    # 함수 실행
    result = await deposit_funds(
        player_id=player_id,
        amount=deposit_amount,
        currency=currency,
        wallet_repo=wallet_repo,
        cache_service=cache_service
    )
    
    # 검증
    wallet_repo.get_balance_by_player_id.assert_called_once_with(player_id, currency)
    wallet_repo.create_transaction.assert_called_once_with(
        player_id=player_id,
        amount=deposit_amount,
        currency=currency,
        transaction_type="deposit",
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
    # 결과의 balance가 Decimal 타입인지 확인하고 비교
    assert isinstance(result["balance"], Decimal)
    assert result["balance"] == expected_new_balance 
    assert result["currency"] == currency

@pytest.mark.asyncio
async def test_deposit_funds_invalid_amount():
    """잘못된 입금 금액(0 또는 음수)을 테스트합니다."""
    wallet_repo = AsyncMock()
    cache_service = AsyncMock()
    
    with pytest.raises(InvalidAmountError, match="0보다 커야 합니다"):
        await deposit_funds(
            player_id="user123",
            amount=Decimal("-10.00"),  # 음수 금액
            currency="USD",
            wallet_repo=wallet_repo,
            cache_service=cache_service
        )
    
    with pytest.raises(InvalidAmountError, match="0보다 커야 합니다"):
        await deposit_funds(
            player_id="user123",
            amount=Decimal("0"),  # 0 금액
            currency="USD",
            wallet_repo=wallet_repo,
            cache_service=cache_service
        )
    
    # 저장소 메서드가 호출되지 않았는지 확인
    wallet_repo.get_balance_by_player_id.assert_not_called()
    wallet_repo.create_transaction.assert_not_called()
    wallet_repo.update_balance.assert_not_called()

@pytest.mark.asyncio
async def test_deposit_funds_user_not_found():
    """존재하지 않는 사용자에 대한 입금 시도 테스트"""
    wallet_repo = AsyncMock()
    wallet_repo.get_balance_by_player_id.return_value = None # 사용자를 찾을 수 없음
    player_id = "nonexistent_user"
    
    with pytest.raises(UserNotFoundError, match=f"사용자 ID {player_id}를 찾을 수 없습니다"):
        await deposit_funds(
            player_id=player_id,
            amount=Decimal("50.00"),
            currency="USD",
            wallet_repo=wallet_repo
        )
    
    wallet_repo.get_balance_by_player_id.assert_called_once_with(player_id, "USD")
    wallet_repo.create_transaction.assert_not_called()
    wallet_repo.update_balance.assert_not_called()

@pytest.mark.asyncio
async def test_deposit_funds_update_balance_fails():
    """잔액 업데이트 실패 시나리오 테스트"""
    wallet_repo = AsyncMock()
    cache_service = AsyncMock()
    
    player_id = "user789"
    currency = "EUR"
    current_balance = Decimal("200.00")
    deposit_amount = Decimal("100.00")
    transaction_id = "txn789012"
    
    wallet_repo.get_balance_by_player_id.return_value = current_balance
    wallet_repo.create_transaction.return_value = transaction_id
    wallet_repo.update_balance.return_value = None # 업데이트 실패 시뮬레이션
    
    with pytest.raises(WalletOperationError, match=f"Failed to update balance for player {player_id}"):
        await deposit_funds(
            player_id=player_id,
            amount=deposit_amount,
            currency=currency,
            wallet_repo=wallet_repo,
            cache_service=cache_service
        )
    
    # create_transaction까지는 호출되어야 함
    wallet_repo.create_transaction.assert_called_once()
    # update_balance도 호출은 되었어야 함 (실패했지만)
    wallet_repo.update_balance.assert_called_once()
    # 캐시는 삭제 시도되지 않아야 함 (업데이트 실패 후)
    cache_service.delete.assert_not_called() 