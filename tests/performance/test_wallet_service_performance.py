# tests/performance/test_wallet_service_performance.py
import pytest
import asyncio
import time
import uuid
from decimal import Decimal

# Import necessary helpers and schemas
from tests.conftest import create_test_wallet
from backend.schemas.wallet import CreditRequest, DebitRequest # Import request schemas
from sqlalchemy.ext.asyncio import AsyncSession

# Models and Services (ensure correct imports)
from backend.partners.models import Partner # 경로 수정
from backend.models.domain.wallet import Wallet, Transaction, TransactionType, TransactionStatus
from backend.services.wallet.wallet_service import WalletService
from backend.repositories.wallet_repository import WalletRepository

@pytest.mark.performance # Mark as performance test
@pytest.mark.asyncio
async def test_concurrent_transactions(wallet_service_factory, db_session: AsyncSession):
    """Tests the performance of handling concurrent wallet transactions."""
    # db_session 올바르게 처리
    session = await anext(db_session)
    
    # Create a wallet service instance using the factory
    factory = await wallet_service_factory
    wallet_service = factory()

    # 1. 파트너 엔티티 먼저 생성 및 커밋
    partner = Partner(
        id=uuid.uuid4(),
        code=f"perf-partner-{uuid.uuid4()}",
        name="Perf Test Partner",
        partner_type="OPERATOR",  # Use appropriate Enum value
        status="ACTIVE"           # Use appropriate Enum value
    )
    session.add(partner) # session 변수 사용
    await session.flush()

    # 2. 테스트 지갑 생성 (생성된 파트너 ID 사용)
    test_wallet = create_test_wallet(balance=Decimal("100000.00"))
    test_wallet.partner_id = partner.id # Assign the valid partner ID
    test_wallet.player_id = uuid.uuid4() # Ensure player_id is also set
    session.add(test_wallet)

    # Commit both partner and wallet together
    await session.commit()
    await session.refresh(test_wallet)
    await session.refresh(partner)

    # 동시 트랜잭션 수행 함수
    async def perform_transaction(amount, currency, type_="credit"):
        # Use the appropriate request schema
        if type_ == "credit":
            request = CreditRequest(
                player_id=test_wallet.player_id,
                reference_id=f"PERF-CREDIT-{uuid.uuid4()}",
                amount=amount,
                currency=currency,
                partner_id=test_wallet.partner_id # Assuming schema needs partner_id
            )
            # Ensure the mock service call matches the expected signature
            return await wallet_service.credit(request=request)
        else: # Assuming 'debit'
             request = DebitRequest(
                player_id=test_wallet.player_id,
                reference_id=f"PERF-DEBIT-{uuid.uuid4()}",
                amount=amount,
                currency=currency,
                partner_id=test_wallet.partner_id # Assuming schema needs partner_id
            )
             # Ensure the mock service call matches the expected signature
             return await wallet_service.debit(request=request)

    # 100개의 동시 트랜잭션 생성 (50 credit, 50 debit)
    transaction_count = 100
    tasks = []
    for i in range(transaction_count):
        if i % 2 == 0:
            tasks.append(perform_transaction(Decimal("1.00"), "USD", "credit"))
        else:
            tasks.append(perform_transaction(Decimal("0.50"), "USD", "debit"))

    # 성능 측정 시작
    start_time = time.time()

    # 모든 트랜잭션 동시 실행
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 성능 측정 종료
    end_time = time.time()

    # 결과 분석
    successful = sum(1 for r in results if not isinstance(r, Exception))
    exceptions = [r for r in results if isinstance(r, Exception)]
    if exceptions:
        print("Exceptions occurred during performance test:")
        for exc in exceptions[:5]: # Print first 5 exceptions
            print(f"- {type(exc).__name__}: {exc}")

    print(f"\nPerformance Test: Completed {successful}/{transaction_count} transactions in {end_time - start_time:.2f} seconds")
    assert successful == transaction_count, f"Expected {transaction_count} successful transactions, but got {successful}"

    # Optional: Verify final balance (tricky with concurrency without proper locking)
    # await db_session.refresh(test_wallet)
    # expected_balance = Decimal("100000.00") + (transaction_count / 2 * Decimal("1.00")) - (transaction_count / 2 * Decimal("0.50"))
    # assert test_wallet.balance == expected_balance 