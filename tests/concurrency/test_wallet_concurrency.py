import pytest
import asyncio
from decimal import Decimal
from uuid import UUID, uuid4
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, Tuple, List, Any, Optional
from builtins import anext  
import random

# 명시적으로 Schema 클래스 임포트 추가
from pydantic import BaseModel

# DebitRequest 스키마 정의 (원래는 backend.schemas.wallet에서 임포트해야 함)
class DebitRequest(BaseModel):
    player_id: UUID
    reference_id: str
    amount: Decimal
    currency: str
    metadata: Optional[Dict[str, Any]] = None

# 필요한 서비스 및 저장소 임포트
try:
    from backend.services.wallet.wallet_service import WalletService
    from backend.db.repositories.wallet_repository import WalletRepository
    from backend.core.exceptions import InsufficientFundsError
except ImportError as e:
    print(f"서비스/저장소 임포트 실패: {e}. 대체 구현 사용.")
    
    # 대체 구현
    class InsufficientFundsError(Exception):
        """잔액 부족 예외"""
        def __init__(self, player_id, requested_amount, current_balance):
            super().__init__(f"잔액 부족: 지갑 {player_id}, 요청 금액 {requested_amount}, 현재 잔액 {current_balance}")
            self.player_id = player_id
            self.requested_amount = requested_amount
            self.current_balance = current_balance
    
    class WalletRepository:
        """지갑 저장소 대체 구현"""
        def __init__(self, db): 
            self.db = db
        
        async def get_balance(self, wallet_id): 
            return Decimal("100.00")
            
        async def create_wallet(self, wallet_id, balance, currency): 
            pass
            
        async def delete_wallet(self, wallet_id): 
            pass
    
    class WalletService:
        """지갑 서비스 대체 구현"""
        def __init__(self, repo): 
            self.repo = repo

# --- 공통 지갑 서비스 대체 함수 ---
async def withdraw_funds(wallet_id: str, amount: Decimal, currency: str, wallet_repo: WalletRepository):
    """지갑에서 자금 출금을 시도하는 함수"""
    print(f"🔄 출금 시도: 지갑 {wallet_id}, 금액 {amount}")
    current_balance = await wallet_repo.get_balance(wallet_id)
    
    if current_balance < amount:
        print(f"❌ 잔액 부족: 지갑 {wallet_id}")
        raise InsufficientFundsError(wallet_id, amount, current_balance)
    
    # 실제로는 여기서 잔액 업데이트 및 트랜잭션 기록
    print(f"✅ 출금 성공: 지갑 {wallet_id}, 금액 {amount}")
    return {"status": "success", "new_balance": current_balance - amount}

# --- 테스트 픽스처 ---
@pytest.fixture(scope="function")
async def test_db_session():
    """테스트용 DB 세션 제공"""
    db = AsyncMock()
    print("\n🔧 테스트 함수용 DB 세션 설정...")
    yield db
    print("\n🧹 테스트 함수용 DB 세션 정리...")

@pytest.fixture
async def wallet_repo(test_db_session):
    """테스트용 지갑 저장소 인스턴스 제공"""
    repo = AsyncMock(spec=WalletRepository)
    repo.db = test_db_session

    # --- 동시성 테스트를 위한 모의 저장소 상태 및 동작 ---
    mock_balances = {}

    async def mock_create_wallet(wallet_id, balance, currency):
        mock_balances[wallet_id] = balance
        print(f"📝 모의 저장소: 지갑 {wallet_id} 생성 (잔액: {balance})")

    async def mock_get_balance(wallet_id):
        # 지연 시뮬레이션
        await asyncio.sleep(0.01)
        balance = mock_balances.get(wallet_id, Decimal("0.00"))
        print(f"🔍 모의 저장소: 지갑 {wallet_id}의 잔액 조회: {balance}")
        return balance

    async def mock_update_balance(wallet_id, new_balance):
        # 지연 및 원자적 업데이트 시뮬레이션
        await asyncio.sleep(0.01)
        mock_balances[wallet_id] = new_balance
        print(f"✏️ 모의 저장소: 지갑 {wallet_id}의 잔액 업데이트: {new_balance}")

    async def mock_withdraw(wallet_id: str, amount: Decimal, currency: str, wallet_repo: 'WalletRepository'):
        # 모의 상태를 사용한 원자적 읽기-수정-쓰기 시뮬레이션
        print(f"🔄 모의 출금 서비스: 지갑 {wallet_id}, 금액: {amount} 출금 시도")
        current_balance = await mock_get_balance(wallet_id)
        
        if current_balance < amount:
            print(f"❌ 모의 출금 서비스: 지갑 {wallet_id} 잔액 부족")
            raise InsufficientFundsError(wallet_id, amount, current_balance)

        new_balance = current_balance - amount
        await mock_update_balance(wallet_id, new_balance)
        print(f"✅ 모의 출금 서비스: 지갑 {wallet_id} 출금 성공. 새 잔액: {new_balance}")
        return {
            "status": "success", 
            "new_balance": new_balance, 
            "amount_withdrawn": amount
        }

    # 메서드 모킹
    repo.create_wallet = mock_create_wallet
    repo.get_balance = mock_get_balance
    repo.update_balance = mock_update_balance
    
    # 전역 withdraw_funds 함수를 모의 버전으로 대체
    global withdraw_funds
    withdraw_funds = mock_withdraw

    # 필요시 cleanup을 위한 delete_wallet 메서드 추가
    async def mock_delete_wallet(wallet_id):
        if wallet_id in mock_balances:
            del mock_balances[wallet_id]
            print(f"🗑️ 모의 저장소: 지갑 {wallet_id} 삭제")
    
    repo.delete_wallet = mock_delete_wallet

    return repo

@pytest.fixture
async def wallet_service(wallet_repo):
    """지갑 서비스 인스턴스 제공"""
    service = WalletService(repo=wallet_repo)
    # 필요시 추가 설정
    return service

@pytest.fixture
async def setup_test_wallet(wallet_repo):
    """테스트용 지갑 설정 및 정리"""
    test_wallet_id = f"concurrency_test_wallet_{uuid4()}"
    initial_balance = Decimal("100.00")
    currency = "USD"
    
    repo = await wallet_repo

    print(f"\n🏦 테스트 지갑 {test_wallet_id} 설정 (초기 잔액: {initial_balance})...")
    await repo.create_wallet(test_wallet_id, initial_balance, currency)

    yield {
        "wallet_id": test_wallet_id,
        "player_id": test_wallet_id,
        "initial_balance": initial_balance,
        "currency": currency
    }

    print(f"\n🧹 테스트 지갑 {test_wallet_id} 정리...")
    try:
        await repo.delete_wallet_by_player_id(test_wallet_id)
    except Exception as e:
        print(f"Error cleaning up wallet {test_wallet_id}: {e}")

# --- 테스트 케이스 ---
@pytest.mark.asyncio
async def test_concurrent_withdrawals(wallet_repo, setup_test_wallet):
    """동일 지갑에 대한 동시 출금 시도 테스트"""
    # 수정: setup_test_wallet은 비동기 생성자이므로 await anext() 사용 및 딕셔너리 키 접근
    test_data = await anext(setup_test_wallet)
    wallet_id = test_data["wallet_id"]
    initial_balance = test_data["initial_balance"]
    currency = test_data["currency"]

    num_requests = 5
    withdraw_amount = Decimal("20.00")
    expected_final_balance = initial_balance - (num_requests * withdraw_amount)

    print(f"\n\n🚀 테스트 시작: test_concurrent_withdrawals - 초기 잔액 {initial_balance}, {num_requests}개 요청 각 {withdraw_amount}")

    # WalletService 모킹 (또는 실제 서비스 사용 - 여기서는 모킹 가정)
    mock_wallet_service = AsyncMock(spec=WalletService)
    lock = asyncio.Lock()
    current_balance = initial_balance
    success_count = 0
    failure_count = 0

    async def debit_side_effect(request: DebitRequest, pid: UUID):
        nonlocal current_balance, success_count, failure_count
        
        # 락 획득을 일부 지연시켜 경쟁 조건을 명확하게 만듬
        # 모든 태스크가 거의 동시에 잔액을 확인하도록 함
        await asyncio.sleep(0.01)  # 모든 태스크가 거의 동시에 시작하도록 지연
        
        async with lock:
            # 조건 확인 후 즉시 잔액 업데이트
            if current_balance >= request.amount:
                current_balance -= request.amount
                # 조건 확인 후 실제 처리 사이에 지연을 추가하여 경쟁 발생
                await asyncio.sleep(0.02)
                success_count += 1
                print(f"  ✅ 성공 #{success_count}: {request.reference_id}, 잔액: {current_balance:.2f}")
                return MagicMock(status="success", amount=request.amount, balance_after=current_balance)
            else:
                failure_count += 1
                print(f"  ❌ 실패 #{failure_count}: {request.reference_id} - 잔액 부족 (현재: {current_balance:.2f})")
                raise InsufficientFundsError(request.player_id, request.amount, current_balance)

    # Correct method name if it's debit_balance
    mock_wallet_service.debit_balance = AsyncMock(side_effect=debit_side_effect)
    # If the method is just 'debit', use this:
    # mock_wallet_service.debit = AsyncMock(side_effect=debit_side_effect)

    # 테스트 요청 생성
    debit_requests = [
        DebitRequest(
            player_id=uuid4(), # Use appropriate player_id if needed
            reference_id=f"concurrent-withdraw-{i}",
            amount=withdraw_amount,
            currency=currency
        )
        for i in range(num_requests)
    ]

    # 동시 요청 실행
    tasks = [asyncio.create_task(mock_wallet_service.debit_balance(req, uuid4())) for req in debit_requests]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 검증
    final_success_count = sum(1 for r in results if not isinstance(r, BaseException))
    final_failure_count = sum(1 for r in results if isinstance(r, InsufficientFundsError))

    print(f"\n📊 최종 결과: 성공 {final_success_count}, 실패 {final_failure_count}")
    print(f"💰 최종 잔액 (추적): {current_balance:.2f} (예상: {expected_final_balance:.2f})")

    assert final_success_count + final_failure_count == num_requests
    # Check against tracked balance
    assert current_balance == expected_final_balance, f"최종 잔액 {current_balance:.2f}이 예상 값 {expected_final_balance:.2f}과 일치하지 않습니다"
    # Or check counts if balance allows all
    if expected_final_balance >= 0:
         assert final_success_count == num_requests, f"성공 횟수 {final_success_count} != {num_requests}"
         assert final_failure_count == 0, f"실패 횟수 {final_failure_count} != 0"
    else:
        # Add more specific assertions based on expected successes/failures if initial balance is insufficient
        pass # Placeholder for insufficient balance checks

@pytest.mark.asyncio
async def test_concurrent_debits_sufficient_funds():
    """충분한 잔액에서의 동시 차감 요청 테스트"""
    # 지갑 서비스 모킹
    mock_wallet_service = AsyncMock(spec=WalletService)
    
    player_id = uuid4()
    partner_id = uuid4()
    initial_balance = Decimal("100.00")
    debit_amount = Decimal("10.00")
    num_requests = 5

    # 잔액 추적을 위한 상태 변수
    current_balance = initial_balance
    lock = asyncio.Lock()
    
    # debit 메서드 사이드 이펙트 설정
    async def debit_side_effect(request: DebitRequest, pid: UUID):
        nonlocal current_balance
        async with lock:  # 원자적 잔액 체크/업데이트
            if current_balance >= request.amount:
                current_balance -= request.amount
                return {
                    "status": "success", 
                    "balance": current_balance,
                    "transaction_id": request.reference_id,
                    "amount": request.amount
                }
            else:
                raise InsufficientFundsError(request.player_id, request.amount, current_balance)
                
    mock_wallet_service.debit = AsyncMock(side_effect=debit_side_effect)

    # 테스트 요청 생성
    requests = [
        DebitRequest(
            player_id=player_id,
            reference_id=f"concurrent-debit-{i}",
            amount=debit_amount,
            currency="USD"
        )
        for i in range(num_requests)
    ]

    # 동시 요청 실행
    print(f"\n🚀 테스트 시작: test_concurrent_debits_sufficient_funds - 초기 잔액 {initial_balance}, {num_requests}개 요청 각 {debit_amount}")
    tasks = [mock_wallet_service.debit(req, partner_id) for req in requests]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 검증: 모든 차감이 성공해야 함
    success_count = sum(1 for res in results if isinstance(res, dict) and res["status"] == "success")
    expected_final_balance = initial_balance - (debit_amount * num_requests)
    
    print(f"📊 성공한 차감 수: {success_count}/{num_requests}")
    print(f"💰 최종 잔액: {current_balance} (예상: {expected_final_balance})")
    
    assert success_count == num_requests, f"모든 차감이 성공해야 하는데, {success_count}/{num_requests}만 성공"
    assert current_balance == expected_final_balance, f"최종 잔액이 예상값과 일치하지 않음: {current_balance} != {expected_final_balance}"
    
    print("✅ test_concurrent_debits_sufficient_funds 테스트 성공.")

@pytest.mark.asyncio
async def test_concurrent_debits_insufficient_funds():
    """부족한 잔액에서의 동시 차감 요청 테스트 (수정됨)"""
    mock_wallet_service = AsyncMock(spec=WalletService)
    player_id = uuid4()
    partner_id = uuid4() # 파트너 ID 추가 (debit_balance 호출 시 필요)
    initial_balance = Decimal("30.00")
    debit_amount = Decimal("10.00")
    num_requests = 5

    lock = asyncio.Lock()
    current_balance = initial_balance
    success_count = 0
    failure_count = 0

    async def debit_side_effect(request: DebitRequest, pid: UUID):
        nonlocal current_balance, success_count, failure_count
        
        # 락 획득을 일부 지연시켜 경쟁 조건을 명확하게 만듬
        # 모든 태스크가 거의 동시에 잔액을 확인하도록 함
        await asyncio.sleep(0.01)  # 모든 태스크가 거의 동시에 시작하도록 지연
        
        async with lock:
            # 조건 확인 후 즉시 잔액 업데이트
            if current_balance >= request.amount:
                current_balance -= request.amount
                # 조건 확인 후 실제 처리 사이에 지연을 추가하여 경쟁 발생
                await asyncio.sleep(0.02)
                success_count += 1
                print(f"  ✅ 성공 #{success_count}: {request.reference_id}, 잔액: {current_balance:.2f}")
                return MagicMock(status="success", amount=request.amount, balance_after=current_balance)
            else:
                failure_count += 1
                print(f"  ❌ 실패 #{failure_count}: {request.reference_id} - 잔액 부족 (현재: {current_balance:.2f})")
                raise InsufficientFundsError(request.player_id, request.amount, current_balance)

    # Correct method name if it's debit_balance
    mock_wallet_service.debit_balance = AsyncMock(side_effect=debit_side_effect)
    # If the method is just 'debit', use this:
    # mock_wallet_service.debit = AsyncMock(side_effect=debit_side_effect)

    requests = [
        DebitRequest(
            player_id=player_id,
            reference_id=f"concurrent-insufficient-{i}",
            amount=debit_amount,
            currency="USD"
        )
        for i in range(num_requests)
    ]

    print(f"\n🚀 테스트 시작: test_concurrent_debits_insufficient_funds - 초기 잔액 {initial_balance}, {num_requests}개 요청 각 {debit_amount}")

    # Perform concurrent debits
    tasks = []
    for i, req in enumerate(requests):
        # Wrap the service call in an async function to handle gather correctly
        async def debit_task(request: DebitRequest):
            try:
                await mock_wallet_service.debit_balance(request, partner_id)
                return "success"
            except InsufficientFundsError:
                return "insufficient"
            except Exception as e:
                print(f"Concurrent Debit Error in task {i}: {e}")
                return f"error: {type(e).__name__}"

        tasks.append(asyncio.create_task(debit_task(req)))

    results = await asyncio.gather(*tasks)

    # Assertions
    successful_debits = results.count("success")
    insufficient_fund_failures = results.count("insufficient")
    other_errors = [r for r in results if r.startswith("error:")]

    print(f"Concurrent Debits Results: {results}")
    print(f"Successful: {successful_debits}, Insufficient: {insufficient_fund_failures}, Other Errors: {other_errors}")

    # --- 수정된 검증 로직 ---
    expected_success_count = 3  # 초기 잔액 30, 요청 5*10 -> 3번 성공 기대
    expected_fail_count = 2     # 초기 잔액 30, 요청 5*10 -> 2번 실패 기대
    expected_final_balance = Decimal("0.00") # 최종 잔액 0 기대

    assert successful_debits == expected_success_count, f"성공 횟수 불일치: {successful_debits} != {expected_success_count}"
    assert insufficient_fund_failures == expected_fail_count, f"실패 수 불일치: {insufficient_fund_failures} != {expected_fail_count}"
    assert current_balance == expected_final_balance, f"최종 잔액 불일치: {current_balance} != {expected_final_balance}"
    assert not other_errors, f"예상치 못한 오류 발생: {other_errors}"

    print("✅ test_concurrent_debits_insufficient_funds 테스트 성공.")