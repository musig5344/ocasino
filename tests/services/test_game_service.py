"""
게임 서비스 테스트
"""
import pytest
from uuid import UUID, uuid4
from decimal import Decimal
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

from backend.services.game.game_service import GameService
from backend.models.domain.game import Game, GameProvider, GameSession, GameTransaction
from backend.schemas.game import GameLaunchRequest
from backend.core.exceptions import ValidationError

# 테스트 데이터
@pytest.fixture
def game_data():
    """테스트용 게임 데이터"""
    return {
        "id": uuid4(),
        "provider_id": uuid4(),
        "game_code": "test-slot",
        "name": "Test Slot Game",
        "category": "slots",
        "status": "active",
        "rtp": Decimal("96.5"),
        "min_bet": Decimal("0.10"),
        "max_bet": Decimal("100.00"),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

@pytest.fixture
def provider_data():
    """테스트용 게임 제공자 데이터"""
    return {
        "id": uuid4(),
        "code": "test-provider",
        "name": "Test Provider",
        "status": "active",
        "integration_type": "direct",
        "api_endpoint": "https://api.testprovider.com",
        "api_key": "test_api_key",
        "api_secret": "test_api_secret",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

@pytest.fixture
def session_data():
    """테스트용 게임 세션 데이터"""
    return {
        "id": uuid4(),
        "player_id": uuid4(),
        "partner_id": uuid4(),
        "game_id": uuid4(),
        "token": "test-session-token",
        "status": "active",
        "start_time": datetime.utcnow(),
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
def game_service(db_session):
    """게임 서비스 인스턴스"""
    service = GameService(db_session)
    
    # 리포지토리 모의 객체 생성
    service.game_repo = AsyncMock()
    service.wallet_repo = AsyncMock()
    
    # 지갑 서비스 모의 객체 생성
    service.wallet_service = AsyncMock()
    
    return service

@pytest.mark.asyncio
async def test_get_game(game_service, game_data):
    """게임 조회 테스트"""
    # 모의 리포지토리 설정
    game = Game(**game_data)
    game_service.game_repo.get_game_by_id.return_value = game
    
    # 함수 호출
    result = await game_service.get_game(game_data["id"])
    
    # 검증
    assert result == game
    game_service.game_repo.get_game_by_id.assert_called_with(game_data["id"])

@pytest.mark.asyncio
async def test_get_provider(game_service, provider_data):
    """게임 제공자 조회 테스트"""
    # 모의 리포지토리 설정
    provider = GameProvider(**provider_data)
    game_service.game_repo.get_provider_by_id.return_value = provider
    
    # 함수 호출
    result = await game_service.get_provider(provider_data["id"])
    
    # 검증
    assert result == provider
    game_service.game_repo.get_provider_by_id.assert_called_with(provider_data["id"])

@pytest.mark.asyncio
async def test_launch_game_direct(game_service, game_data, provider_data, session_data):
    """직접 통합 게임 실행 테스트"""
    # 모의 객체 설정
    game = Game(**game_data)
    provider = GameProvider(**provider_data)
    wallet = MagicMock()
    wallet.balance = Decimal("1000.00")
    wallet.currency = "USD"
    
    game_service.game_repo.get_game_by_id.return_value = game
    game_service.game_repo.get_provider_by_id.return_value = provider
    game_service.wallet_service.ensure_wallet_exists.return_value = (wallet, False)
    
    # 새 세션 생성 모의 설정
    session = GameSession(**session_data)
    game_service.game_repo.create_session.return_value = session
    
    # 게임 실행 요청 생성
    request = GameLaunchRequest(
        player_id=session_data["player_id"],
        game_id=game_data["id"],
        currency="USD",
        language="en"
    )
    
    # 함수 호출
    result = await game_service.launch_game(request, session_data["partner_id"])
    
    # 검증
    assert result.token == session.token
    assert "https://api.testprovider.com/launch" in result.game_url
    
    game_service.game_repo.get_game_by_id.assert_called_with(game_data["id"])
    game_service.game_repo.get_provider_by_id.assert_called_with(game_data["provider_id"])
    game_service.wallet_service.ensure_wallet_exists.assert_called_with(
        session_data["player_id"], session_data["partner_id"], "USD"
    )
    game_service.game_repo.create_session.assert_called_once()

@pytest.mark.asyncio
async def test_process_bet_callback(game_service, session_data):
    """베팅 콜백 처리 테스트"""
    # 모의 세션 설정
    session = GameSession(**session_data)
    session.session_data = {"currency": "USD"}
    
    # 트랜잭션 응답 모의 설정
    transaction_response = MagicMock()
    transaction_response.reference_id = "TEST-BET-123"
    transaction_response.amount = Decimal("10.00")
    transaction_response.currency = "USD"
    transaction_response.balance = Decimal("990.00")
    
    game_service.wallet_service.debit.return_value = transaction_response
    
    # 게임 트랜잭션 생성 모의 설정
    game_service._create_game_transaction = AsyncMock()
    
    # 콜백 데이터 생성
    callback_data = {
        "token": session.token,
        "action": "bet",
        "round_id": "ROUND-123",
        "reference_id": "TEST-BET-123",
        "amount": "10.00",
        "game_data": {"lines": 10, "bet_per_line": "1.00"}
    }
    
    # 함수 호출
    result = await game_service._process_bet_callback(callback_data, session, session_data["partner_id"])
    
    # 검증
    assert result["status"] == "success"
    assert result["balance"] == "990.00"
    assert result["currency"] == "USD"
    assert result["transaction_id"] == "TEST-BET-123"
    
    game_service.wallet_service.debit.assert_called_once()
    game_service._create_game_transaction.assert_called_once()

@pytest.mark.asyncio
async def test_process_win_callback(game_service, session_data):
    """승리 콜백 처리 테스트"""
    # 모의 세션 설정
    session = GameSession(**session_data)
    session.session_data = {"currency": "USD"}
    
    # 트랜잭션 응답 모의 설정
    transaction_response = MagicMock()
    transaction_response.reference_id = "TEST-WIN-123"
    transaction_response.amount = Decimal("20.00")
    transaction_response.currency = "USD"
    transaction_response.balance = Decimal("1010.00")
    
    game_service.wallet_service.credit.return_value = transaction_response
    
    # 게임 트랜잭션 생성 모의 설정
    game_service._create_game_transaction = AsyncMock()
    
    # 콜백 데이터 생성
    callback_data = {
        "token": session.token,
        "action": "win",
        "round_id": "ROUND-123",
        "reference_id": "TEST-WIN-123",
        "amount": "20.00",
        "game_data": {"win_type": "free_spins", "multiplier": 2}
    }
    
    # 함수 호출
    result = await game_service._process_win_callback(callback_data, session, session_data["partner_id"])
    
    # 검증
    assert result["status"] == "success"
    assert result["balance"] == "1010.00"
    assert result["currency"] == "USD"
    assert result["transaction_id"] == "TEST-WIN-123"
    
    game_service.wallet_service.credit.assert_called_once()
    game_service._create_game_transaction.assert_called_once()

@pytest.mark.asyncio
async def test_process_refund_callback(game_service, session_data):
    """환불 콜백 처리 테스트"""
    # 모의 세션 설정
    session = GameSession(**session_data)
    session.session_data = {"currency": "USD"}
    
    # 트랜잭션 응답 모의 설정
    transaction_response = MagicMock()
    transaction_response.reference_id = "TEST-REFUND-123"
    transaction_response.amount = Decimal("10.00")
    transaction_response.currency = "USD"
    transaction_response.balance = Decimal("1000.00")
    
    game_service.wallet_service.rollback.return_value = transaction_response
    
    # 게임 트랜잭션 생성 모의 설정
    game_service._create_game_transaction = AsyncMock()
    
    # 콜백 데이터 생성
    callback_data = {
        "token": session.token,
        "action": "refund",
        "round_id": "ROUND-123",
        "reference_id": "TEST-REFUND-123",
        "original_reference_id": "TEST-BET-123"
    }
    
    # 함수 호출
    result = await game_service._process_refund_callback(callback_data, session, session_data["partner_id"])
    
    # 검증
    assert result["status"] == "success"
    assert result["balance"] == "1000.00"
    assert result["currency"] == "USD"
    assert result["transaction_id"] == "TEST-REFUND-123"
    
    game_service.wallet_service.rollback.assert_called_once()
    game_service._create_game_transaction.assert_called_once()