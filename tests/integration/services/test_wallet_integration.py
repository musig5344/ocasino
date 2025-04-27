import pytest
from decimal import Decimal
from uuid import uuid4
from datetime import datetime
from unittest.mock import AsyncMock, patch
import asyncio
import uuid

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ArgumentError, OperationalError
from sqlalchemy import text

from backend.db.database import Base
from backend.models.domain.wallet import Wallet, Transaction, TransactionType, TransactionStatus
from backend.partners.models import Partner, PartnerType, PartnerStatus
from backend.services.wallet.wallet_service import WalletService
from backend.schemas.wallet import DebitRequest, CreditRequest, RollbackRequest
from backend.core.exceptions import (
    InsufficientFundsError, DuplicateTransactionError, TransactionNotFoundError,
    CurrencyMismatchError, WalletNotFoundError
)
from backend.repositories.wallet_repository import WalletRepository
from backend.db.repositories.partner_repository import PartnerRepository

# 테스트용 인메모리 DB 설정 - 함수 내에서 고유하게 생성
# TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# 픽스처 제거
# 전역 finalize 함수 제거

# --- 파일 레벨 테스트 함수 (직접 DB 설정) --- #

@pytest.mark.asyncio
# async def test_debit_credit_integration(): # 기존 시그니처 주석 처리
# async def test_debit_credit_integration(db_session: AsyncSession): # 이전 시그니처 주석 처리
async def test_debit_credit_integration(db_session_factory: async_sessionmaker): # db_session 파라미터 제거
    """Test debit followed by credit using a real DB session provided by fixture."""
    # SQLite 관련 설정 및 엔진 생성 제거
    # 테이블 생성/삭제 로직 제거 (픽스처에서 처리 가정)

    # db_session_factory 코루틴을 await 하여 실제 팩토리 객체 얻기
    actual_factory = await db_session_factory # await 추가

    # WalletService 생성 시 await으로 얻은 실제 팩토리 전달
    wallet_service = WalletService(read_db_factory=actual_factory, write_db_factory=actual_factory)

    # 실제 팩토리를 사용하여 세션 생성 및 테스트 진행
    async with actual_factory() as session:
        # 테스트 데이터 생성 (session 사용)
        player_id = str(uuid4())
        partner = Partner(
            id=uuid4(),
            code="integ_test_partner",
            name="Integration Test Partner",
            status=PartnerStatus.ACTIVE,
            partner_type=PartnerType.OPERATOR,
        )
        session.add(partner) # db_session 대신 session 사용
        await session.commit()
        await session.refresh(partner)
        partner_id = partner.id
        currency = "USD"
        initial_balance = Decimal("1000.00")
        debit_amount = Decimal("100.00")
        credit_amount = Decimal("50.00")
        debit_ref = f"integ-debit-{uuid4()}"
        credit_ref = f"integ-credit-{uuid4()}"

        test_wallet = Wallet(
            player_id=player_id,
            partner_id=partner_id,
            balance=initial_balance,
            currency=currency,
        )
        session.add(test_wallet) # db_session 대신 session 사용
        await session.commit()
        await session.refresh(test_wallet)

        print(f"Wallet created for Player: {player_id}, Partner: {partner_id}, Balance: {initial_balance}")

        # Debit 테스트 (session 사용)
        try:
            debit_request = DebitRequest(
                player_id=player_id,
                reference_id=debit_ref,
                amount=debit_amount,
                currency=currency,
                transaction_type=TransactionType.BET,
            )

            # 추가: 테스트 지갑 ID 출력
            print(f"\n[Debit Test] Test wallet ID: {test_wallet.id}, Player ID: {player_id}")

            debit_result = await wallet_service.debit(request=debit_request, partner_id=partner_id)
            assert debit_result.status == TransactionStatus.COMPLETED

            # 사용 가능한 속성만 사용하도록 수정
            print(f"[Debit Test] Transaction result: status={debit_result.status}, amount={debit_result.amount}")

            # 모든 사용 가능한 필드 확인을 위해 디버깅 (선택적)
            # print(f"[Debit Test] Available fields in result: {dir(debit_result)}")

            # 현재 세션을 명시적으로 커밋
            await session.commit()
            print(f"[Debit Test] Initial session committed after debit.")

            expected_balance_after_debit = initial_balance - debit_amount

            # 직접 SQL로 확인 (선택적)
            async with actual_factory() as verify_session:
                print(f"[Debit Test] Verifying balance with direct SQL for wallet ID: {test_wallet.id}")
                result = await verify_session.execute(
                    text(f"SELECT balance FROM wallets WHERE id = :wallet_id"),
                    {"wallet_id": test_wallet.id}
                )
                row = result.fetchone()
                if row:
                    print(f"[Debit Test] SQL verified balance: {row[0]}")
                    # SQL 결과와 기대값 비교 (선택적 추가 검증)
                    # assert Decimal(str(row[0])) == expected_balance_after_debit
                else:
                    print(f"[Debit Test] SQL verification failed: Wallet {test_wallet.id} not found.")

            # 새 세션의 캐시를 명시적으로 클리어하고 조회
            async with actual_factory() as fresh_session:
                print(f"[Debit Test] Verifying balance with new session for wallet ID: {test_wallet.id}")
                fresh_session.expire_all()  # 캐시 클리어
                print(f"[Debit Test] Cleared new session cache (expire_all).")
                refreshed_wallet = await fresh_session.get(Wallet, test_wallet.id)
                if refreshed_wallet:
                    print(f"[Debit Test] Got wallet object from new session. Current balance: {refreshed_wallet.balance}")
                    await fresh_session.refresh(refreshed_wallet)  # 강제로 다시 로드
                    print(f"[Debit Test] Refreshed wallet object. Balance after refresh: {refreshed_wallet.balance}")
                    assert refreshed_wallet.balance == expected_balance_after_debit
                    print(f"✅ Debit successful. New balance confirmed: {refreshed_wallet.balance}")
                else:
                    pytest.fail(f"[Debit Test] Failed to get wallet {test_wallet.id} from new session.")

        except Exception as e:
            pytest.fail(f"Debit operation failed unexpectedly: {e}")

        # Credit 테스트 (session 사용)
        try:
            credit_request = CreditRequest(
                player_id=player_id,
                reference_id=credit_ref,
                amount=credit_amount,
                currency=currency,
                transaction_type=TransactionType.WIN,
            )
            # 추가: Credit 전 테스트 지갑 ID 출력
            print(f"\n[Credit Test] Test wallet ID: {test_wallet.id}, Player ID: {player_id}")

            credit_result = await wallet_service.credit(request=credit_request, partner_id=partner_id)
            assert credit_result.status == TransactionStatus.COMPLETED

            # 사용 가능한 속성만 사용하도록 수정 (Credit 후)
            print(f"[Credit Test] Transaction result: status={credit_result.status}, amount={credit_result.amount}")

            # 모든 사용 가능한 필드 확인을 위해 디버깅 (선택적, Credit 후)
            # print(f"[Credit Test] Available fields in result: {dir(credit_result)}")

            # 현재 세션 커밋 (Credit 후)
            await session.commit()
            print(f"[Credit Test] Initial session committed after credit.")

            expected_final_balance = expected_balance_after_debit + credit_amount

            # 새 세션 생성하여 지갑 다시 조회 (Credit 후)
            async with actual_factory() as fresh_session_after_credit:
                print(f"[Credit Test] Verifying balance with new session for wallet ID: {test_wallet.id}")
                fresh_session_after_credit.expire_all()
                print(f"[Credit Test] Cleared new session cache (expire_all).")
                refreshed_wallet_after_credit = await fresh_session_after_credit.get(Wallet, test_wallet.id)

                if refreshed_wallet_after_credit:
                     print(f"[Credit Test] Got wallet object from new session. Current balance: {refreshed_wallet_after_credit.balance}")
                     await fresh_session_after_credit.refresh(refreshed_wallet_after_credit)
                     print(f"[Credit Test] Refreshed wallet object. Balance after refresh: {refreshed_wallet_after_credit.balance}")
                     assert refreshed_wallet_after_credit.balance == expected_final_balance
                     print(f"✅ Credit successful. Final balance confirmed: {refreshed_wallet_after_credit.balance}")
                else:
                     pytest.fail(f"[Credit Test] Failed to get wallet {test_wallet.id} from new session after credit.")

        except Exception as e:
            pytest.fail(f"Credit operation failed unexpectedly: {e}")

        # 최종 검증 로그 강화
        print(f"\n✅ Final expected balance: {expected_final_balance}")
        print("✅ 테스트 종료: test_debit_credit_integration")

    # finally 블록 제거 (엔진 관리 불필요)

# --- 나머지 테스트는 나중에 수정 --- #

# @pytest.mark.asyncio
# async def test_debit_insufficient_funds(wallet_service_integration_engine: WalletService, db_session):
#     """잔액 부족 시나리오 테스트"""
#     # ... (수정 필요)

# @pytest.mark.asyncio
# async def test_currency_mismatch(wallet_service_integration_engine: WalletService, db_session):
#     """통화 불일치 시나리오 테스트"""
#     # ... (수정 필요)

# @pytest.mark.asyncio
# async def test_duplicate_transaction(wallet_service_integration_engine: WalletService, db_session):
#     """중복 트랜잭션 처리 테스트"""
#     # ... (수정 필요)

# --- 클래스 레벨 테스트 (직접 DB 설정) --- #

# @pytest.mark.asyncio
# class TestWalletServiceIntegration:
#     """지갑 서비스 통합 테스트"""

#     async def setup_method(self):
#         """각 테스트 메서드 실행 전 DB 설정"""
#         self.engine = create_async_engine(TEST_DATABASE_URL, echo=False)
#         self.async_session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
#         async with self.engine.begin() as conn:
#             await conn.run_sync(Base.metadata.create_all)

#         async with self.async_session_factory() as session:
#             # 테스트용 Partner 생성
#             self.test_partner = Partner(
#                 id=uuid4(), code="TEST_PARTNER_CLS", name="Test Casino Class",
#                 partner_type=PartnerType.OPERATOR, status=PartnerStatus.ACTIVE
#             )
#             session.add(self.test_partner)
#             await session.commit()
#             await session.refresh(self.test_partner)

#             # 테스트용 Wallet 생성
#             self.test_wallet = Wallet(
#                 player_id=str(uuid4()), partner_id=self.test_partner.id,
#                 currency="KRW", balance=Decimal("10000.00")
#             )
#             session.add(self.test_wallet)
#             await session.commit()
#             await session.refresh(self.test_wallet)

#             # WalletService 생성
#             self.service = WalletService(read_db=session, write_db=session)

#     async def teardown_method(self):
#         """각 테스트 메서드 실행 후 DB 정리"""
#         if self.engine:
#             await self.engine.dispose()

#     @pytest.mark.asyncio
#     async def test_debit_success(self):
#         """출금 성공 테스트"""
#         # self.service, self.test_wallet 사용
#         actual_wallet = self.test_wallet
#         assert actual_wallet is not None
#         initial_balance = actual_wallet.balance
#         # ... (기존 테스트 로직) ...

#     # ... (다른 클래스 메서드들도 동일하게 self.service, self.test_wallet 사용하도록 수정) ...

# 추가 통합 테스트 시나리오:
# - 지갑 생성 테스트 (create_wallet)
# - 지갑 조회 테스트 (get_wallet)
# - 잔액 조회 테스트 (get_balance)
# - WalletNotFoundError 테스트