import pytest
from unittest.mock import AsyncMock, patch
from decimal import Decimal

# 필요한 예외 클래스 정의
class InvalidAmountError(Exception):
    pass

class UserNotFoundError(Exception):
    pass

class WalletOperationError(Exception):
    pass

class GameSessionNotFoundError(Exception):
    pass

# 분리된 record_win 함수 정의
async def record_win(
    player_id: str, 
    amount: Decimal, 
    currency: str, 
    game_id: str, 
    session_id: str,
    wallet_repo, 
    game_session_service=None,
    cache_service=None
):
    """
    플레이어의 승리 금액을 기록하고 지갑에 추가하는 함수
    
    Args:
        player_id (str): 플레이어 ID
        amount (Decimal): 승리 금액
        currency (str): 통화 단위
        game_id (str): 게임 ID
        session_id (str): 게임 세션 ID
        wallet_repo: 지갑 저장소 객체
        game_session_service: 게임 세션 서비스 객체 (기본값: None)
        cache_service: 캐시 서비스 객체 (기본값: None)
        
    Returns:
        dict: 업데이트된 잔액 정보
        
    Raises:
        InvalidAmountError: 승리 금액이 유효하지 않은 경우
        UserNotFoundError: 플레이어를 찾을 수 없는 경우
        GameSessionNotFoundError: 게임 세션을 찾을 수 없는 경우
        WalletOperationError: 지갑 작업 중 오류 발생
    """
    # 승리 금액 유효성 검사
    if amount <= Decimal("0"):
        raise InvalidAmountError("승리 금액은 0보다 커야 합니다")
    
    # 게임 세션 유효성 검사 (선택 사항)
    if game_session_service:
        session = await game_session_service.get_session(session_id)
        if not session:
            raise GameSessionNotFoundError(f"게임 세션 ID {session_id}를 찾을 수 없습니다")
        # Optionally, add more session checks (status, game_id match)

    # 기존 잔액 조회
    current_balance = await wallet_repo.get_balance_by_player_id(player_id, currency)
    if current_balance is None:
        raise UserNotFoundError(f"플레이어 ID {player_id}를 찾을 수 없습니다")
    
    # 새 잔액 계산
    new_balance = current_balance + amount
    
    # 트랜잭션 생성
    transaction_id = await wallet_repo.create_transaction(
        player_id=player_id,
        amount=amount,
        currency=currency,
        transaction_type="win",
        status="completed",
        metadata={
            "game_id": game_id,
            "session_id": session_id
        }
    )
    
    # 잔액 업데이트
    updated_balance_data = await wallet_repo.update_balance(
        player_id=player_id,
        new_balance=new_balance,
        currency=currency,
        transaction_id=transaction_id
    )

    if updated_balance_data is None:
         raise WalletOperationError(f"Failed to update balance for player {player_id} after win")

    # 캐시 업데이트 (캐시 서비스가 있는 경우)
    if cache_service:
        try:
            await cache_service.delete(f"balance:{player_id}:{currency}")
        except Exception as e:
            print(f"Warning: Failed to delete cache for {player_id}:{currency} after win - {e}")
            pass
    
    return updated_balance_data

# 테스트 케이스
@pytest.mark.asyncio
async def test_record_win_success():
    """정상적인 승리 기록 처리를 테스트합니다."""
    # Mock 객체 생성
    wallet_repo = AsyncMock()
    game_session_service = AsyncMock()
    cache_service = AsyncMock()
    
    # Mock 동작 설정
    player_id = "user123"
    currency = "USD"
    game_id = "game456"
    session_id = "session789"
    current_balance = Decimal("100.00")
    win_amount = Decimal("50.00")
    transaction_id = "txn_win_123"
    expected_new_balance = Decimal("150.00")
    
    game_session_service.get_session.return_value = {"id": session_id, "game_id": game_id, "status": "active"}
    wallet_repo.get_balance_by_player_id.return_value = current_balance
    wallet_repo.create_transaction.return_value = transaction_id
    wallet_repo.update_balance.return_value = {
        "player_id": player_id,
        "balance": expected_new_balance,
        "currency": currency,
        "updated_at": "2023-01-01T12:00:00Z"
    }
    
    # 함수 실행
    result = await record_win(
        player_id=player_id,
        amount=win_amount,
        currency=currency,
        game_id=game_id,
        session_id=session_id,
        wallet_repo=wallet_repo,
        game_session_service=game_session_service,
        cache_service=cache_service
    )
    
    # 검증
    game_session_service.get_session.assert_called_once_with(session_id)
    wallet_repo.get_balance_by_player_id.assert_called_once_with(player_id, currency)
    wallet_repo.create_transaction.assert_called_once_with(
        player_id=player_id,
        amount=win_amount,
        currency=currency,
        transaction_type="win",
        status="completed",
        metadata={
            "game_id": game_id,
            "session_id": session_id
        }
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
async def test_record_win_without_game_session_service():
    """게임 세션 서비스 없이 승리 기록 처리를 테스트합니다."""
    wallet_repo = AsyncMock()
    cache_service = AsyncMock()
    
    player_id = "user123"
    currency = "USD"
    game_id = "game456"
    session_id = "session789"
    current_balance = Decimal("100.00")
    win_amount = Decimal("50.00")
    transaction_id = "txn_win_no_gss"
    expected_new_balance = Decimal("150.00")
    
    wallet_repo.get_balance_by_player_id.return_value = current_balance
    wallet_repo.create_transaction.return_value = transaction_id
    wallet_repo.update_balance.return_value = {
        "player_id": player_id,
        "balance": expected_new_balance,
        "currency": currency,
        "updated_at": "2023-01-01T12:00:00Z"
    }
    
    # game_session_service=None 으로 함수 실행
    result = await record_win(
        player_id=player_id,
        amount=win_amount,
        currency=currency,
        game_id=game_id,
        session_id=session_id,
        wallet_repo=wallet_repo,
        game_session_service=None, # Explicitly None
        cache_service=cache_service
    )
    
    # 검증 (game_session_service는 호출 안 됨)
    wallet_repo.get_balance_by_player_id.assert_called_once_with(player_id, currency)
    wallet_repo.create_transaction.assert_called_once_with(
        player_id=player_id,
        amount=win_amount,
        currency=currency,
        transaction_type="win",
        status="completed",
        metadata={
            "game_id": game_id,
            "session_id": session_id
        }
    )
    wallet_repo.update_balance.assert_called_once()
    cache_service.delete.assert_called_once()

    assert isinstance(result["balance"], Decimal)
    assert result["balance"] == expected_new_balance

@pytest.mark.asyncio
async def test_record_win_invalid_amount():
    """잘못된 승리 금액(0 또는 음수)을 테스트합니다."""
    wallet_repo = AsyncMock()
    game_session_service = AsyncMock()
    
    with pytest.raises(InvalidAmountError, match="0보다 커야 합니다"):
        await record_win(
            player_id="user123",
            amount=Decimal("-10.00"),
            currency="USD",
            game_id="game456",
            session_id="session789",
            wallet_repo=wallet_repo,
            game_session_service=game_session_service
        )
    
    with pytest.raises(InvalidAmountError, match="0보다 커야 합니다"):
        await record_win(
            player_id="user123",
            amount=Decimal("0"),
            currency="USD",
            game_id="game456",
            session_id="session789",
            wallet_repo=wallet_repo,
            game_session_service=game_session_service
        )
    
    game_session_service.get_session.assert_not_called()
    wallet_repo.get_balance_by_player_id.assert_not_called()
    wallet_repo.create_transaction.assert_not_called()
    wallet_repo.update_balance.assert_not_called()

@pytest.mark.asyncio
async def test_record_win_session_not_found():
    """존재하지 않는 게임 세션에 대한 테스트"""
    wallet_repo = AsyncMock()
    game_session_service = AsyncMock()
    game_session_service.get_session.return_value = None # 세션 없음
    session_id = "invalid_session"
    
    with pytest.raises(GameSessionNotFoundError, match=f"게임 세션 ID {session_id}를 찾을 수 없습니다"):
        await record_win(
            player_id="user123",
            amount=Decimal("50.00"),
            currency="USD",
            game_id="game456",
            session_id=session_id,
            wallet_repo=wallet_repo,
            game_session_service=game_session_service
        )
    
    game_session_service.get_session.assert_called_once_with(session_id)
    wallet_repo.get_balance_by_player_id.assert_not_called()
    wallet_repo.create_transaction.assert_not_called()
    wallet_repo.update_balance.assert_not_called()

@pytest.mark.asyncio
async def test_record_win_user_not_found():
    """존재하지 않는 플레이어에 대한 테스트"""
    wallet_repo = AsyncMock()
    game_session_service = AsyncMock()
    player_id = "nonexistent_user"

    game_session_service.get_session.return_value = {"id": "session789", "status": "active"} # 세션은 존재
    wallet_repo.get_balance_by_player_id.return_value = None # 플레이어 없음
    
    with pytest.raises(UserNotFoundError, match=f"플레이어 ID {player_id}를 찾을 수 없습니다"):
        await record_win(
            player_id=player_id,
            amount=Decimal("50.00"),
            currency="USD",
            game_id="game456",
            session_id="session789",
            wallet_repo=wallet_repo,
            game_session_service=game_session_service
        )
    
    game_session_service.get_session.assert_called_once_with("session789")
    wallet_repo.get_balance_by_player_id.assert_called_once_with(player_id, "USD")
    wallet_repo.create_transaction.assert_not_called()
    wallet_repo.update_balance.assert_not_called() 