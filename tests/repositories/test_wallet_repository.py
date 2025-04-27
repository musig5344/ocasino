import pytest
import uuid
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
import asyncio # anext 사용 위해 추가 (Python 3.10 이상) or from async_generator import anext

# Adjust imports based on your project structure
from backend.models.domain.wallet import Wallet, Transaction, TransactionType, TransactionStatus
from backend.partners.models import Partner
from backend.db.repositories.wallet_repository import WalletRepository
from backend.utils.encryption import encrypt_aes_gcm, decrypt_aes_gcm

# Import necessary components for local fixture
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.core.config import settings
from backend.db.database import Base # Assuming models inherit from Base

# --- Start: Local Fixtures for Isolation ---
TEST_DB_URL_LOCAL = settings.TEST_DATABASE_URL if hasattr(settings, 'TEST_DATABASE_URL') and settings.TEST_DATABASE_URL else "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="function")
async def db_engine_local():
    """Provides a database engine scoped to each function in this file."""
    connect_args = {"check_same_thread": False} if "sqlite" in TEST_DB_URL_LOCAL else {}
    engine = create_async_engine(TEST_DB_URL_LOCAL, echo=False, connect_args=connect_args)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

@pytest.fixture(scope="function")
async def db_session(db_engine_local): # Use the local engine
    """Provides a clean session with rollback for each test function in this file.
       Uses the SQLAlchemy 2.0 async_sessionmaker style.
    """
    async_session_factory = async_sessionmaker(
        db_engine_local, # Use the local engine fixture
        class_=AsyncSession,
        expire_on_commit=False
    )
    async with async_session_factory() as session:
        async with session.begin(): # Start a transaction
            yield session
            # Rollback is handled automatically by the context manager

# --- End: Local Fixtures for Isolation ---


@pytest.mark.asyncio
async def test_update_wallet_balance(wallet_repo, db_session, test_wallet_instance):
    # 세션 객체 가져오기
    session = await anext(db_session)

    initial_balance = test_wallet_instance.balance
    wallet_id = test_wallet_instance.id

    print(f"\n🔄 테스트 시작: test_update_wallet_balance")
    print(f"지갑 ID: {wallet_id}, 초기 잔액: {initial_balance}")

    # 1. Debit (출금)
    debit_amount = Decimal("15.00")
    await wallet_repo.update_wallet_balance(session, wallet_id, -debit_amount)
    await session.commit()
    print(f"Debit 실행: 금액={debit_amount}")

    wallet_after_debit = await wallet_repo.get_wallet_by_id(session, wallet_id)
    assert wallet_after_debit.balance == initial_balance - debit_amount
    print(f"Debit 후 잔액 확인 완료: {wallet_after_debit.balance}")

    # 2. Credit (입금)
    credit_amount = Decimal("30.00")
    await wallet_repo.update_wallet_balance(session, wallet_id, credit_amount)
    await session.commit()
    print(f"Credit 실행: 금액={credit_amount}")

    wallet_after_credit = await wallet_repo.get_wallet_by_id(session, wallet_id)
    assert wallet_after_credit.balance == initial_balance - debit_amount + credit_amount
    print(f"Credit 후 잔액 확인 완료: {wallet_after_credit.balance}")

    print("✅ 테스트 종료: test_update_wallet_balance")

# Add more repository tests: get_wallet_by_player_id, get_transaction_by_reference, etc.
# Test edge cases: concurrent updates (requires locking tests), invalid inputs handled by DB constraints. 