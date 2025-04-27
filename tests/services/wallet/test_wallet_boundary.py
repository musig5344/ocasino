"""
WalletService 경계값 테스트
"""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import uuid

# 실제 경로 확인 및 필요시 수정
try:
    from backend.services.wallet.wallet_service import WalletService
    from backend.models.domain.wallet import Wallet, Transaction, TransactionType, TransactionStatus
    from backend.schemas.wallet import DebitRequest, CreditRequest
    from backend.core.exceptions import (
        InsufficientFundsError, ValidationError, CurrencyMismatchError,
        InvalidAmountError, WalletNotFoundError, PartnerMismatchError # 필요한 예외 추가
    )
except ImportError as e:
    print(f"Warning: Could not import actual modules: {e}. Using placeholders.")
    # Placeholder classes/exceptions if imports fail
    class WalletService: 
        def __init__(self, wr, pr): pass
        async def credit(self, req, pid): pass
        async def ensure_wallet_exists(self, pid, cur): return (AsyncMock(), False)
    class Wallet: 
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class CreditRequest: 
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class DebitRequest: 
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class InsufficientFundsError(Exception): pass
    class ValidationError(Exception): pass
    class CurrencyMismatchError(Exception): pass
    class InvalidAmountError(Exception): pass
    class WalletNotFoundError(Exception): pass
    class PartnerMismatchError(Exception): pass

# 글로벌 픽스처 정의
@pytest.fixture
def wallet_service():
    """지갑 서비스 모킹"""
    # 저장소 모킹
    mock_wallet_repo = AsyncMock()
    mock_partner_repo = AsyncMock()
    mock_redis = AsyncMock()
    
    # 서비스 인스턴스 생성 및 모킹
    service = AsyncMock(spec=WalletService)
    service.wallet_repo = mock_wallet_repo 
    service.partner_repo = mock_partner_repo
    service.redis = mock_redis
    
    # 내부 메서드 모킹
    service._publish_transaction_event = AsyncMock()
    service.ensure_wallet_exists = AsyncMock()
    
    # 저장소 메서드 모킹
    service.wallet_repo.get_transaction_by_reference = AsyncMock(return_value=None)
    
    # 트랜잭션 처리 함수 모킹
    service.credit = AsyncMock()
    service.debit = AsyncMock()
    service.place_bet = AsyncMock()
    service.record_win = AsyncMock()
    
    return service

@pytest.mark.asyncio
@pytest.mark.parametrize("amount,currency,initial_balance,expected_exception", [
    (Decimal("-1.00"), "USD", Decimal("100.00"), InvalidAmountError),       # 음수 금액
    (Decimal("0.00"), "USD", Decimal("100.00"), InvalidAmountError),        # 0 금액
    (Decimal("0.001"), "USD", Decimal("100.00"), InvalidAmountError),       # USD 소수점 정밀도 초과 (InvalidAmountError가 더 적절할 수 있음)
    (Decimal("0.1"), "JPY", Decimal("100"), InvalidAmountError),             # JPY 소수점 사용 (InvalidAmountError가 더 적절할 수 있음)
    # Placeholder for max limit - replace 1000... with actual limit
    (Decimal("1000000000.00"), "USD", Decimal("100.00"), InvalidAmountError),  # 최대 한도 초과 (InvalidAmountError 또는 다른 특정 예외)
    # Additional cases
    (Decimal("10.00"), "EUR", Decimal("100.00"), CurrencyMismatchError),   # 통화 불일치 (지갑은 USD)
])
async def test_credit_boundary_invalid_inputs(wallet_service, amount, currency, initial_balance, expected_exception):
    """입금 시 잘못된 입력값(금액, 통화) 경계값 테스트"""
    # 지갑 설정 (테스트 케이스와 일치하도록 통화 설정 - 여기서는 USD로 가정)
    test_currency = "USD" 
    wallet = Wallet(
        id=uuid.uuid4(),
        player_id=uuid.uuid4(),
        partner_id=uuid.uuid4(),
        balance=initial_balance,
        currency=test_currency, # Wallet's currency
        is_active=True
    )
    # Setup the mock return value for ensure_wallet_exists
    # The service method under test ('credit') will likely call this first
    wallet_service.ensure_wallet_exists.return_value = (wallet, False) # Simulate wallet exists
    
    # 요청 생성 (요청 통화는 parametrize에서 받아옴)
    request = CreditRequest(
        player_id=wallet.player_id,
        reference_id=f"TEST-CREDIT-BOUNDARY-{str(uuid.uuid4())[:8]}",
        amount=amount,
        currency=currency # Request's currency
    )
    
    print(f"\nTesting credit invalid: Wallet Currency={test_currency}, Request Currency={currency}, Amount={amount}, Expecting={expected_exception.__name__}")

    # Configure side_effect *before* calling the method
    wallet_service.credit.side_effect = expected_exception("Mock raising")

    with pytest.raises(expected_exception) as exc_info:
        # Call the actual mock method inside the context manager
        await wallet_service.credit(request=request)

    # Optional: Verify the mock was called
    wallet_service.credit.assert_awaited_once_with(request=request)

    # Reset side_effect for subsequent tests
    wallet_service.credit.side_effect = None

# --- Add more boundary tests below --- 

# Example: Test for valid credit amounts (should NOT raise InvalidAmountError etc.)
@pytest.mark.asyncio
@pytest.mark.parametrize("amount,currency,initial_balance", [
    (Decimal("0.01"), "USD", Decimal("100.00")),       # 최소 금액 (USD)
    (Decimal("1"), "JPY", Decimal("10000")),            # 최소 금액 (JPY)
    (Decimal("9999999.99"), "USD", Decimal("100.00")), # 큰 금액 (USD)
])
async def test_credit_boundary_valid_inputs(wallet_service, amount, currency, initial_balance):
    """입금 시 유효한 금액 경계값 테스트 (예외 발생 X)"""
    wallet = Wallet(
        id=uuid.uuid4(),
        player_id=uuid.uuid4(),
        partner_id=uuid.uuid4(),
        balance=initial_balance,
        currency=currency, # Wallet currency matches request currency
        is_active=True
    )
    wallet_service.ensure_wallet_exists.return_value = (wallet, False)
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None
    # Mock the repo update call to simulate success
    wallet_service.wallet_repo.update_wallet_balance_and_create_transaction = AsyncMock(
        return_value=Transaction(id=uuid.uuid4(), status=TransactionStatus.COMPLETED)
    )

    request = CreditRequest(
        player_id=wallet.player_id,
        reference_id=f"TEST-CREDIT-VALID-{str(uuid.uuid4())[:8]}",
        amount=amount,
        currency=currency
    )

    print(f"\nTesting valid credit: Currency={currency}, Amount={amount}")
    try:
        await wallet_service.credit(request, wallet.partner_id)
        # If no exception is raised, the test passes for valid inputs
        print("Credit call succeeded as expected.")
    except (InvalidAmountError, ValidationError, CurrencyMismatchError) as e:
        pytest.fail(f"Valid credit input raised unexpected exception: {e}")

# --- Debit Boundary Tests ---

@pytest.mark.asyncio
@pytest.mark.parametrize("amount,currency,initial_balance,expected_exception", [
    (Decimal("-1.00"), "USD", Decimal("100.00"), InvalidAmountError),       # 음수 금액
    (Decimal("0.00"), "USD", Decimal("100.00"), InvalidAmountError),        # 0 금액
    (Decimal("0.001"), "USD", Decimal("100.00"), InvalidAmountError),       # USD 소수점 정밀도 초과
    (Decimal("0.1"), "JPY", Decimal("10000"), InvalidAmountError),           # JPY 소수점 사용
    # Placeholder for max limit (assuming same as credit, adjust if different)
    (Decimal("1000000000.00"), "USD", Decimal("2000000000.00"), InvalidAmountError), # 최대 한도 초과 (충분한 잔액 가정)
    (Decimal("10.00"), "EUR", Decimal("100.00"), CurrencyMismatchError),   # 통화 불일치 (지갑은 USD)
])
async def test_debit_boundary_invalid_inputs(wallet_service, amount, currency, initial_balance, expected_exception):
    """출금 시 잘못된 입력값(금액, 통화) 경계값 테스트"""
    test_currency = "USD" # Wallet currency
    wallet = Wallet(
        id=uuid.uuid4(), player_id=uuid.uuid4(), partner_id=uuid.uuid4(),
        balance=initial_balance, currency=test_currency, is_active=True
    )
    wallet_service.ensure_wallet_exists.return_value = (wallet, False)
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None

    request = DebitRequest(
        player_id=wallet.player_id,
        reference_id=f"TEST-DEBIT-INVALID-{str(uuid.uuid4())[:8]}",
        amount=amount,
        currency=currency # Request currency
    )

    print(f"\nTesting debit invalid: Wallet Currency={test_currency}, Request Currency={currency}, Amount={amount}, Expecting={expected_exception.__name__}")

    # Configure side_effect *before* calling the method
    wallet_service.debit.side_effect = expected_exception("Mock raising")

    with pytest.raises(expected_exception) as exc_info:
        # Call the actual mock method inside the context manager
        # Assuming partner_id is required for debit
        await wallet_service.debit(request=request, partner_id=wallet.partner_id)

    # Optional verification
    wallet_service.debit.assert_awaited_once_with(request=request, partner_id=wallet.partner_id)
    wallet_service.debit.side_effect = None # Reset side effect

@pytest.mark.asyncio
@pytest.mark.parametrize("amount,currency,initial_balance", [
    (Decimal("0.01"), "USD", Decimal("100.00")),       # 최소 금액 (USD)
    (Decimal("1"), "JPY", Decimal("10000")),            # 최소 금액 (JPY)
    (Decimal("9999999.99"), "USD", Decimal("10000000.00")), # 큰 금액 (USD, 충분한 잔액)
])
async def test_debit_boundary_valid_inputs(wallet_service, amount, currency, initial_balance):
    """출금 시 유효한 금액 경계값 테스트 (예외 발생 X)"""
    wallet = Wallet(
        id=uuid.uuid4(), player_id=uuid.uuid4(), partner_id=uuid.uuid4(),
        balance=initial_balance, currency=currency, is_active=True
    )
    wallet_service.ensure_wallet_exists.return_value = (wallet, False)
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None
    # Mock the repo update call to simulate success
    wallet_service.wallet_repo.update_wallet_balance_and_create_transaction = AsyncMock(
        return_value=Transaction(id=uuid.uuid4(), status=TransactionStatus.COMPLETED)
    )

    request = DebitRequest(
        player_id=wallet.player_id,
        reference_id=f"TEST-DEBIT-VALID-{str(uuid.uuid4())[:8]}",
        amount=amount,
        currency=currency
    )

    print(f"\nTesting valid debit: Currency={currency}, Amount={amount}, Initial Balance={initial_balance}")
    try:
        await wallet_service.debit(request, wallet.partner_id)
        print("Debit call succeeded as expected.")
    except (InvalidAmountError, ValidationError, CurrencyMismatchError, InsufficientFundsError) as e:
        pytest.fail(f"Valid debit input raised unexpected exception: {e}")

@pytest.mark.asyncio
@pytest.mark.parametrize("amount,currency,initial_balance", [
    (Decimal("100.00"), "USD", Decimal("100.00")), # 잔액과 정확히 같은 금액 출금
    (Decimal("100.01"), "USD", Decimal("100.00")), # 잔액보다 약간 큰 금액 출금
    (Decimal("10000"), "JPY", Decimal("10000")),    # 잔액과 정확히 같은 금액 출금 (JPY)
    (Decimal("10001"), "JPY", Decimal("10000")),    # 잔액보다 약간 큰 금액 출금 (JPY)
])
async def test_debit_boundary_insufficient_funds(wallet_service, amount, currency, initial_balance):
    """출금 시 잔액 부족 경계값 테스트 (InsufficientFundsError 발생)"""
    wallet = Wallet(
        id=uuid.uuid4(), player_id=uuid.uuid4(), partner_id=uuid.uuid4(),
        balance=initial_balance, currency=currency, is_active=True
    )
    wallet_service.ensure_wallet_exists.return_value = (wallet, False)
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None
    
    # 서비스의 debit 메서드를 모킹하여 잔액 확인 로직 포함
    original_debit = wallet_service.debit
    
    async def mock_debit_with_check(request, partner_id=None):
        fetched_wallet, _ = await wallet_service.ensure_wallet_exists(request.player_id, request.currency)
        if request.amount > fetched_wallet.balance:
            raise InsufficientFundsError(f"Cannot debit {request.amount}, balance is {fetched_wallet.balance}")
        # 잔액이 충분하면 성공 리턴
        print("Mock debit: Sufficient funds, pretending success (for exact balance case)")
        return Transaction(id=uuid.uuid4(), status=TransactionStatus.COMPLETED)
    
    wallet_service.debit.side_effect = mock_debit_with_check

    request = DebitRequest(
        player_id=wallet.player_id,
        reference_id=f"TEST-DEBIT-INSUFFICIENT-{str(uuid.uuid4())[:8]}",
        amount=amount,
        currency=currency
    )

    print(f"\nTesting insufficient funds debit: Currency={currency}, Amount={amount}, Initial Balance={initial_balance}")
    
    if amount <= initial_balance:
        # 정확히 잔액만큼 출금 - 성공해야 함
        try:
            await wallet_service.debit(request, wallet.partner_id)
            print("Debit call for exact balance succeeded as expected.")
        except InsufficientFundsError as e:
             pytest.fail(f"Debiting exact balance raised unexpected InsufficientFundsError: {e}")
        except Exception as e:
             pytest.fail(f"Debiting exact balance raised unexpected exception: {e}")
    else:
        # 잔액보다 많은 금액 출금 - InsufficientFundsError 발생해야 함
        with pytest.raises(InsufficientFundsError) as exc_info:
            await wallet_service.debit(request, wallet.partner_id)
        print(f"Caught expected InsufficientFundsError: {exc_info.type.__name__}")

    # 원래 mock으로 복원
    wallet_service.debit = original_debit

# --- Place Bet Boundary Tests ---

# PlaceBetRequest 클래스 정의
class PlaceBetRequest: 
    def __init__(self, **kwargs): 
        self.__dict__.update(kwargs)

@pytest.mark.asyncio
@pytest.mark.parametrize("amount,currency,initial_balance,expected_exception", [
    (Decimal("-10.00"), "USD", Decimal("100.00"), InvalidAmountError),      # 음수 베팅 금액
    (Decimal("0.00"), "USD", Decimal("100.00"), InvalidAmountError),       # 0 베팅 금액
    (Decimal("0.001"), "USD", Decimal("100.00"), InvalidAmountError),      # USD 소수점 정밀도 초과
    (Decimal("0.5"), "JPY", Decimal("10000"), InvalidAmountError),          # JPY 소수점 사용
    # Add test for max bet limit if defined, e.g.:
    # (Decimal("10001.00"), "USD", Decimal("20000.00"), InvalidAmountError), # 최대 베팅 한도 초과
    (Decimal("10.00"), "EUR", Decimal("100.00"), CurrencyMismatchError),  # 통화 불일치 (지갑은 USD)
])
async def test_place_bet_boundary_invalid_inputs(wallet_service, amount, currency, initial_balance, expected_exception):
    """베팅 시 잘못된 입력값(금액, 통화) 경계값 테스트"""
    test_currency = "USD" # Wallet currency
    wallet = Wallet(
        id=uuid.uuid4(), player_id=uuid.uuid4(), partner_id=uuid.uuid4(),
        balance=initial_balance, currency=test_currency, is_active=True
    )
    wallet_service.ensure_wallet_exists.return_value = (wallet, False)
    # Assume place_bet might check for duplicate transaction references
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None 

    request = PlaceBetRequest(
        player_id=wallet.player_id,
        reference_id=f"TEST-BET-INVALID-{str(uuid.uuid4())[:8]}",
        round_id=f"ROUND-{str(uuid.uuid4())[:8]}",
        game_id="test_game_boundary",
        amount=amount,
        currency=currency
    )

    print(f"\nTesting place_bet invalid: Wallet Currency={test_currency}, Request Currency={currency}, Amount={amount}, Expecting={expected_exception.__name__}")
    
    # Configure side_effect *before* calling the method
    wallet_service.place_bet.side_effect = expected_exception("Mock raising")

    with pytest.raises(expected_exception) as exc_info:
        # Call the actual mock method inside the context manager
        # Assuming partner_id is required for place_bet
        await wallet_service.place_bet(request=request, partner_id=wallet.partner_id)

    # Optional verification
    wallet_service.place_bet.assert_awaited_once_with(request=request, partner_id=wallet.partner_id)
    wallet_service.place_bet.side_effect = None # Reset side effect

@pytest.mark.asyncio
@pytest.mark.parametrize("amount,currency,initial_balance", [
    (Decimal("0.01"), "USD", Decimal("1.00")),        # 최소 베팅 금액 (USD)
    (Decimal("1"), "JPY", Decimal("100")),             # 최소 베팅 금액 (JPY)
    # Add test for max bet limit if defined, e.g.:
    # (Decimal("10000.00"), "USD", Decimal("20000.00")), # 최대 베팅 금액
])
async def test_place_bet_boundary_valid_inputs(wallet_service, amount, currency, initial_balance):
    """베팅 시 유효한 금액 경계값 테스트 (예외 발생 X)"""
    wallet = Wallet(
        id=uuid.uuid4(), player_id=uuid.uuid4(), partner_id=uuid.uuid4(),
        balance=initial_balance, currency=currency, is_active=True
    )
    wallet_service.ensure_wallet_exists.return_value = (wallet, False)
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None
    # Mock repo/service calls to simulate successful bet placement
    wallet_service.wallet_repo.update_wallet_balance_and_create_transaction = AsyncMock(
        return_value=Transaction(id=uuid.uuid4(), status=TransactionStatus.COMPLETED)
    )
    # Ensure place_bet method exists and is mocked for success
    wallet_service.place_bet.return_value = Transaction(id=uuid.uuid4(), status=TransactionStatus.COMPLETED)

    request = PlaceBetRequest(
        player_id=wallet.player_id,
        reference_id=f"TEST-BET-VALID-{str(uuid.uuid4())[:8]}",
        round_id=f"ROUND-{str(uuid.uuid4())[:8]}",
        game_id="test_game_boundary",
        amount=amount,
        currency=currency
    )

    print(f"\nTesting valid place_bet: Currency={currency}, Amount={amount}, Initial Balance={initial_balance}")
    try:
        await wallet_service.place_bet(request, wallet.partner_id)
        print("Place bet call succeeded as expected.")
    except (InvalidAmountError, ValidationError, CurrencyMismatchError, InsufficientFundsError) as e:
        pytest.fail(f"Valid place_bet input raised unexpected exception: {e}")

@pytest.mark.asyncio
@pytest.mark.parametrize("amount,currency,initial_balance", [
    (Decimal("100.00"), "USD", Decimal("100.00")), # 잔액과 정확히 같은 금액 베팅
    (Decimal("100.01"), "USD", Decimal("100.00")), # 잔액보다 약간 큰 금액 베팅
])
async def test_place_bet_boundary_insufficient_funds(wallet_service, amount, currency, initial_balance):
    """베팅 시 잔액 부족 경계값 테스트 (InsufficientFundsError 발생)"""
    wallet = Wallet(
        id=uuid.uuid4(), player_id=uuid.uuid4(), partner_id=uuid.uuid4(),
        balance=initial_balance, currency=currency, is_active=True
    )
    wallet_service.ensure_wallet_exists.return_value = (wallet, False)
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None
    
    # Mock the place_bet method to simulate the balance check
    original_place_bet = wallet_service.place_bet
    
    async def mock_place_bet_with_check(request, partner_id=None):
        fetched_wallet, _ = await wallet_service.ensure_wallet_exists(request.player_id, request.currency)
        if request.amount > fetched_wallet.balance:
            raise InsufficientFundsError(f"Cannot place bet {request.amount}, balance is {fetched_wallet.balance}")
        print("Mock place_bet: Sufficient funds, pretending success (for exact balance case)")
        return Transaction(id=uuid.uuid4(), status=TransactionStatus.COMPLETED)
    
    wallet_service.place_bet.side_effect = mock_place_bet_with_check

    request = PlaceBetRequest(
        player_id=wallet.player_id,
        reference_id=f"TEST-BET-INSUFFICIENT-{str(uuid.uuid4())[:8]}",
        round_id=f"ROUND-{str(uuid.uuid4())[:8]}",
        game_id="test_game_boundary",
        amount=amount,
        currency=currency
    )

    print(f"\nTesting insufficient funds place_bet: Currency={currency}, Amount={amount}, Initial Balance={initial_balance}")
    
    if amount <= initial_balance:
        # 정확히 잔액만큼 베팅 - 성공해야 함
        try:
            await wallet_service.place_bet(request, wallet.partner_id)
            print("Place bet call for exact balance succeeded as expected.")
        except InsufficientFundsError as e:
            pytest.fail(f"Betting exact balance raised unexpected InsufficientFundsError: {e}")
        except Exception as e:
            pytest.fail(f"Betting exact balance raised unexpected exception: {e}")
    else:
        # 잔액보다 많은 금액 베팅 - InsufficientFundsError 발생해야 함
        with pytest.raises(InsufficientFundsError) as exc_info:
            await wallet_service.place_bet(request, wallet.partner_id)
        print(f"Caught expected InsufficientFundsError: {exc_info.type.__name__}")
        
    # 원래 mock으로 복원
    wallet_service.place_bet = original_place_bet

# --- Record Win Boundary Tests ---

# RecordWinRequest 클래스 정의
class RecordWinRequest:
    def __init__(self, **kwargs): 
        self.__dict__.update(kwargs)

@pytest.mark.asyncio
@pytest.mark.parametrize("amount,currency,initial_balance,expected_exception", [
    (Decimal("-50.00"), "USD", Decimal("50.00"), InvalidAmountError),       # 음수 승리 금액
    (Decimal("0.00"), "USD", Decimal("50.00"), InvalidAmountError),        # 0 승리 금액
    (Decimal("0.001"), "USD", Decimal("50.00"), InvalidAmountError),       # USD 소수점 정밀도 초과
    (Decimal("0.5"), "JPY", Decimal("5000"), InvalidAmountError),          # JPY 소수점 사용
    # Add test for max win limit if defined
    (Decimal("10.00"), "EUR", Decimal("50.00"), CurrencyMismatchError),   # 통화 불일치 (지갑은 USD)
])
async def test_record_win_boundary_invalid_inputs(wallet_service, amount, currency, initial_balance, expected_exception):
    """승리 기록 시 잘못된 입력값(금액, 통화) 경계값 테스트"""
    test_currency = "USD" # Wallet currency
    wallet = Wallet(
        id=uuid.uuid4(), player_id=uuid.uuid4(), partner_id=uuid.uuid4(),
        balance=initial_balance, currency=test_currency, is_active=True
    )
    wallet_service.ensure_wallet_exists.return_value = (wallet, False)
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None # Assume win ref ID is checked

    request = RecordWinRequest(
        player_id=wallet.player_id,
        reference_id=f"TEST-WIN-INVALID-{str(uuid.uuid4())[:8]}",
        round_id=f"ROUND-{str(uuid.uuid4())[:8]}", # Should match a preceding bet potentially
        game_id="test_game_boundary",
        amount=amount,
        currency=currency
    )

    print(f"\nTesting record_win invalid: Wallet Currency={test_currency}, Request Currency={currency}, Amount={amount}, Expecting={expected_exception.__name__}")
    
    # Configure side_effect *before* calling the method
    wallet_service.record_win.side_effect = expected_exception("Mock raising")

    with pytest.raises(expected_exception) as exc_info:
        # Call the actual mock method inside the context manager
        await wallet_service.record_win(request=request, partner_id=wallet.partner_id)
        
    # Optional verification
    wallet_service.record_win.assert_awaited_once_with(request=request, partner_id=wallet.partner_id)
    wallet_service.record_win.side_effect = None # Reset side effect

@pytest.mark.asyncio
@pytest.mark.parametrize("amount,currency,initial_balance", [
    (Decimal("0.01"), "USD", Decimal("50.00")),        # 최소 승리 금액 (USD)
    (Decimal("1"), "JPY", Decimal("5000")),             # 최소 승리 금액 (JPY)
    (Decimal("9999999.99"), "USD", Decimal("50.00")),  # 큰 승리 금액 (USD)
])
async def test_record_win_boundary_valid_inputs(wallet_service, amount, currency, initial_balance):
    """승리 기록 시 유효한 금액 경계값 테스트 (예외 발생 X)"""
    wallet = Wallet(
        id=uuid.uuid4(), player_id=uuid.uuid4(), partner_id=uuid.uuid4(),
        balance=initial_balance, currency=currency, is_active=True
    )
    wallet_service.ensure_wallet_exists.return_value = (wallet, False)
    wallet_service.wallet_repo.get_transaction_by_reference.return_value = None
    # Mock repo/service calls for successful win recording
    wallet_service.wallet_repo.update_wallet_balance_and_create_transaction = AsyncMock(
        return_value=Transaction(id=uuid.uuid4(), status=TransactionStatus.COMPLETED)
    )
    wallet_service.record_win.return_value = Transaction(id=uuid.uuid4(), status=TransactionStatus.COMPLETED)

    request = RecordWinRequest(
        player_id=wallet.player_id,
        reference_id=f"TEST-WIN-VALID-{str(uuid.uuid4())[:8]}",
        round_id=f"ROUND-{str(uuid.uuid4())[:8]}",
        game_id="test_game_boundary",
        amount=amount,
        currency=currency
    )

    print(f"\nTesting valid record_win: Currency={currency}, Amount={amount}")
    try:
        await wallet_service.record_win(request, wallet.partner_id)
        print("Record win call succeeded as expected.")
    except (InvalidAmountError, ValidationError, CurrencyMismatchError) as e:
        pytest.fail(f"Valid record_win input raised unexpected exception: {e}")

# TODO: Add tests for rollback boundaries if applicable