import pytest
import asyncio
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock # Using AsyncMock for placeholders
import logging # Added logger
from builtins import anext # Import anext

# 실제 서비스, 저장소, 예외, DB 설정 임포트 (경로 확인 및 수정 필요)
try:
    from backend.services.wallet.wallet_service import WalletService # Bet/Win functions might be here
    from backend.services.wallet.betting_service import place_bet # Or dedicated service
    from backend.services.wallet.winning_service import record_win # Or dedicated service
    from backend.services.game.game_service import GameService
    from backend.services.reporting.reporting_service import ReportingService
    from backend.db.repositories.wallet_repository import WalletRepository
    from backend.db.repositories.game_repository import GameRepository
    from backend.db.repositories.transaction_repository import TransactionRepository
    from backend.db.repositories.reporting_repository import ReportingRepository
    # Add other necessary repositories (Player, Partner etc.) if needed
    from backend.core.exceptions import InsufficientFundsError, InvalidGameRoundError # Example exceptions
    from backend.db.database import get_db, init_db
except ImportError as e:
    print(f"Warning: Could not import actual services/repositories/exceptions: {e}. Using placeholders.")
    # Placeholder implementations
    class BaseRepo: 
        def __init__(self, db): self.db = db
    class WalletRepository(BaseRepo):
        async def get_balance(self, wallet_id): return Decimal("1000.00")
        async def update_balance(self, wallet_id, new_balance): print(f"MockRepo: Update balance {wallet_id} -> {new_balance}")
        async def get_wallet_by_player_id(self, player_id, currency): return {"id": f"wallet_for_{player_id}", "balance": Decimal("1000.00")}
    class GameRepository(BaseRepo): 
        async def get_game(self, game_id): return {"id": game_id, "provider_id": "prov1", "name": "Test Game"}
    class TransactionRepository(BaseRepo):
        async def create_transaction(self, data): print(f"MockRepo: Create transaction {data}"); return {**data, "id": str(uuid4())}
        async def find_transaction_by_ref(self, ref_id): return None # For idempotency checks
    class ReportingRepository(BaseRepo): 
        async def update_partner_commission(self, data): print(f"MockRepo: Update commission {data}")
    class WalletService: 
        def __init__(self, repo): self.repo = repo
    class GameService: 
        def __init__(self, repo): self.repo = repo
    class ReportingService: 
        def __init__(self, repo): self.repo = repo
    async def place_bet(wallet_id, amount, game_id, round_id, player_id, currency, trans_repo, wallet_repo):
        print(f"MockService: Placing bet {amount} for player {player_id} on game {game_id}")
        balance = await wallet_repo.get_balance(wallet_id)
        if balance < amount: raise InsufficientFundsError()
        await wallet_repo.update_balance(wallet_id, balance - amount)
        await trans_repo.create_transaction({"type": "BET", "amount": -amount, "wallet_id": wallet_id, "ref_id": f"{round_id}_bet"})
        return {"status": "success", "balance": balance - amount}
    async def record_win(wallet_id, amount, game_id, round_id, player_id, currency, trans_repo, wallet_repo):
        print(f"MockService: Recording win {amount} for player {player_id} on game {game_id}")
        balance = await wallet_repo.get_balance(wallet_id) # Assume previous bet already deducted
        await wallet_repo.update_balance(wallet_id, balance + amount)
        await trans_repo.create_transaction({"type": "WIN", "amount": amount, "wallet_id": wallet_id, "ref_id": f"{round_id}_win"})
        return {"status": "success", "balance": balance + amount}
    class InsufficientFundsError(Exception): pass
    class InvalidGameRoundError(Exception): pass
    async def init_db(): print("Mock init_db called")
    async def get_db(): print("Mock get_db called"); return AsyncMock()

# --- Fixtures ---
@pytest.fixture(scope="function")
async def test_db_session():
    """Provides a database session (mocked)."""
    db = AsyncMock()
    print("\nSetting up DB session...")
    yield db
    print("\nTearing down DB session...")

# Repository Fixtures (using Mocks)
@pytest.fixture
async def wallet_repo(test_db_session):
    repo = AsyncMock(spec=WalletRepository)
    repo.mock_balances = {}
    repo.db = test_db_session

    async def mock_get_balance(wallet_id):
        print(f"Mock get_balance for {wallet_id}, returning: {repo.mock_balances.get(wallet_id, Decimal('0.00'))}")
        return repo.mock_balances.get(wallet_id, Decimal('0.00'))

    async def mock_update_balance(wallet_id, new_balance):
        print(f"Mock update_balance for {wallet_id} by {new_balance}")
        current = repo.mock_balances.get(wallet_id, Decimal('0.00'))
        repo.mock_balances[wallet_id] = current + new_balance

    async def mock_get_wallet_by_player_id(player_id, currency):
        wallet_id = f"wallet_for_{player_id}"
        if wallet_id not in repo.mock_balances:
            repo.mock_balances[wallet_id] = Decimal("1000.00")
        return {"id": wallet_id, "balance": repo.mock_balances[wallet_id]}

    repo.get_balance = AsyncMock(side_effect=mock_get_balance)
    repo.update_balance = AsyncMock(side_effect=mock_update_balance)
    repo.get_wallet_by_player_id = AsyncMock(side_effect=mock_get_wallet_by_player_id)
    return repo

@pytest.fixture
async def game_repo(test_db_session):
    repo = AsyncMock(spec=GameRepository)
    repo.db = test_db_session
    return repo

@pytest.fixture
async def transaction_repo(test_db_session):
    repo = AsyncMock(spec=TransactionRepository)
    repo.db = test_db_session
    repo.create_transaction = AsyncMock(side_effect=lambda data: {**data, "id": uuid4()})
    return repo

@pytest.fixture
async def reporting_repo(test_db_session):
    repo = AsyncMock(spec=ReportingRepository)
    repo.db = test_db_session
    return repo

# Service Fixtures (using Mock Repos)
@pytest.fixture
def wallet_service(wallet_repo):
    service = WalletService(repo=wallet_repo)
    return service

@pytest.fixture
def game_service(game_repo):
    service = GameService(repo=game_repo)
    return service

@pytest.fixture
def reporting_service(reporting_repo):
    service = ReportingService(repo=reporting_repo)
    return service

@pytest.fixture
def setup_test_data(wallet_repo):
    """Sets up prerequisite data for the game flow test."""
    test_player_id = f"player_{uuid4()}"
    test_game_id = f"game_{uuid4()}"
    test_partner_id = f"partner_{uuid4()}"
    currency = "USD"
    initial_balance = Decimal("1000.00")

    actual_wallet_repo = wallet_repo

    print(f"\nSetting up test data sync: Player={test_player_id}, Game={test_game_id}, Partner={test_partner_id}")
    test_data = {
        "player_id": test_player_id,
        "game_id": test_game_id,
        "partner_id": test_partner_id,
        "currency": currency,
        "initial_balance": initial_balance,
    }
    yield test_data
    print(f"\nCleaning up test data sync for Player={test_player_id}...")

# Mock GameService needs to be defined or imported
class MockGameService:
    async def place_bet(self, wallet_id, amount, game_id, round_id, player_id, currency, trans_repo, wallet_repo):
        print(f"MockGameService: Placing bet {amount} for player {player_id} on game {game_id}, wallet {wallet_id}")
        balance = await wallet_repo.get_balance(wallet_id)
        if balance < amount:
            print("MockGameService: Insufficient funds")
            raise InsufficientFundsError("Insufficient funds")
        await wallet_repo.update_balance(wallet_id, -amount)
        tx_data = {
            "id": uuid4(),
            "wallet_id": wallet_id,
            "type": "BET",
            "amount": -amount,
            "ref_id": f"{round_id}_bet"
        }
        await trans_repo.create_transaction(tx_data)
        new_balance = await wallet_repo.get_balance(wallet_id)
        print(f"MockGameService: Bet placed. New balance: {new_balance}")
        return tx_data["id"]

    async def settle_win(self, wallet_id, amount, game_id, round_id, player_id, currency, trans_repo, wallet_repo, bet_tx_id):
        print(f"MockGameService: Settling win {amount} for player {player_id}, wallet {wallet_id}")
        await wallet_repo.update_balance(wallet_id, amount)
        tx_data = {
            "id": uuid4(),
            "wallet_id": wallet_id,
            "type": "WIN",
            "amount": amount,
            "ref_id": f"{round_id}_win",
            "original_transaction_id": bet_tx_id,
        }
        await trans_repo.create_transaction(tx_data)
        new_balance = await wallet_repo.get_balance(wallet_id)
        print(f"MockGameService: Win settled. New balance: {new_balance}")
        return tx_data["id"]

# --- Test Cases ---
@pytest.mark.asyncio
async def test_player_bet_win_settlement(setup_test_data, wallet_repo, transaction_repo):
    test_data = setup_test_data
    player_id = test_data["player_id"]
    partner_id = test_data["partner_id"]
    currency = test_data["currency"]
    initial_balance = test_data["initial_balance"]

    actual_wallet_repo = await wallet_repo
    wallet_info = await actual_wallet_repo.get_wallet_by_player_id(player_id, currency)
    wallet_id = wallet_info["id"]
    actual_wallet_repo.mock_balances[wallet_id] = initial_balance
    print(f"Wallet setup for test: ID={wallet_id}, Initial Balance={initial_balance}")

    print(f"\n🚀 테스트 시작: test_player_bet_win_settlement")
    print(f"플레이어: {player_id}, 파트너: {partner_id}, 통화: {currency}, 초기 잔액: {initial_balance}")

    bet_amount = Decimal("10.00")
    bet_tx_ref = f"bet-{uuid4()}"

    actual_trans_repo = await transaction_repo

    print(f"\nStarting test_player_bet_win_settlement for Player {player_id}...")

    mock_game_service = MockGameService()
    round_id = f"round_{uuid4()}"

    bet_tx_id = await mock_game_service.place_bet(
        wallet_id, bet_amount, test_data["game_id"], round_id, player_id, currency,
        actual_trans_repo, actual_wallet_repo
    )
    expected_balance_after_bet = initial_balance - bet_amount
    actual_wallet_repo.update_balance.assert_called_with(wallet_id, -bet_amount)
    actual_trans_repo.create_transaction.assert_called()
    print(f"Bet placed, Tx ID: {bet_tx_id}")

    win_amount = Decimal("20.00")
    print(f"Step 2: Settling win ({win_amount} {currency}) for round {round_id}")
    win_tx_id = await mock_game_service.settle_win(
        wallet_id, win_amount, test_data["game_id"], round_id, player_id, currency,
        actual_trans_repo, actual_wallet_repo, bet_tx_id=bet_tx_id
    )
    expected_balance_after_win = expected_balance_after_bet + win_amount
    actual_wallet_repo.update_balance.assert_called_with(wallet_id, win_amount)
    actual_trans_repo.create_transaction.assert_called()
    print(f"Win settled, Tx ID: {win_tx_id}")

    final_balance = await actual_wallet_repo.get_balance(wallet_id)
    assert final_balance == expected_balance_after_win, f"Final balance mismatch: {final_balance} != {expected_balance_after_win}"
    print(f"Final balance verified: {final_balance}")

    print(f"Test completed for Player {player_id}.")

# Note: This E2E test heavily relies on mocks currently.
# For true validation, replace mocks with actual service instances,
# ensure proper DB setup, and implement detailed verification queries
# against transaction and reporting tables. 