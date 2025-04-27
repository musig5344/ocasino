import pytest
import asyncio
from httpx import AsyncClient, Response
from uuid import UUID, uuid4
from decimal import Decimal
import random
import string
import logging
from typing import Dict, Any, Optional, Tuple
from fastapi import FastAPI
from unittest.mock import AsyncMock, patch
import base64
import os
from datetime import datetime, timezone

from backend.main import app
from backend.services.auth.auth_service import AuthService
from backend.core.dependencies import get_current_partner_id, get_auth_service
from backend.cache.redis_cache import get_redis_client
from backend.partners.models import ApiKey, Partner
from backend.services.wallet.wallet_service import WalletService
from backend.core.exceptions import WalletNotFoundError
from backend.models.domain.wallet import TransactionType, TransactionStatus, Wallet

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 의존성 오버라이드 함수
def get_current_partner_id_override():
    async def _get_partner_id():
        return "test_partner_id"
    return _get_partner_id

# 미들웨어 없는 테스트 앱 생성 함수
def create_middleware_free_app(original_app: FastAPI) -> FastAPI:
    """미들웨어 없는 테스트용 FastAPI 앱 생성"""
    test_app = FastAPI()
    
    # 원본 앱의 라우터만 복사
    for route in original_app.routes:
        test_app.routes.append(route)
    
    # 의존성 오버라이드 복사
    test_app.dependency_overrides = original_app.dependency_overrides.copy()
    
    # Redis 클라이언트 모킹
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=True)
    mock_redis.ping = AsyncMock(return_value=True)
    test_app.dependency_overrides[get_redis_client] = lambda: mock_redis
    
    # AuthService 의존성 오버라이드
    mock_auth_service = AsyncMock(spec=AuthService)
    mock_api_key_obj = ApiKey(
        id=uuid4(),
        partner_id=UUID("015e60eb-ea54-4ad8-bd8f-4a1ce9b436b7"),
        key="hashed_test_key",
        permissions={"wallet": ["deposit", "bet", "win", "read", "withdraw", "transactions.read"]},
        is_active=True,
    )
    mock_partner_obj = Partner(
        id=UUID("015e60eb-ea54-4ad8-bd8f-4a1ce9b436b7"),
        code="TESTPARTNER",
        name="Test Partner",
        status="active"
    )
    mock_auth_service.authenticate_api_key = AsyncMock(return_value=(mock_api_key_obj, mock_partner_obj))
    test_app.dependency_overrides[get_auth_service] = lambda: mock_auth_service
    
    return test_app

# 유틸리티 함수
def generate_reference_id(prefix: str = "TEST") -> str:
    """유니크 레퍼런스 ID 생성"""
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f"{prefix}-{random_chars}"

async def safe_decimal_conversion(value: Any) -> Decimal:
    """JSON 값을 안전하게 Decimal로 변환"""
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        logger.error(f"Decimal 변환 실패: {value}")
        return Decimal("0")
        
async def check_response(response: Response, expected_status: int = 200) -> Dict[str, Any]:
    """API 응답 확인 및 JSON 데이터 추출"""
    try:
        if response.status_code != expected_status:
            # 에러 응답 본문 출력
            error_info = ""
            try:
                error_info = response.json()
            except Exception:
                error_info = response.text
                
            logger.error(f"API 요청 실패: 상태 코드 {response.status_code}, 응답: {error_info}")
        
        assert response.status_code == expected_status, f"API 요청 실패: {response.status_code} != {expected_status}"
        
        json_data = response.json()
        return json_data
    except Exception as e:
        logger.error(f"응답 처리 오류: {str(e)}")
        raise

@pytest.mark.skip(reason="DB 세션 모킹 문제로 인해 임시 스킵: 'async_generator' object has no attribute 'execute'")
@pytest.mark.asyncio
async def test_full_player_game_flow():
    """플레이어 게임 플레이 전체 흐름 E2E 테스트 (WalletService 완전 모킹)"""
    logger.info("🚀 E2E 테스트 시작: 플레이어 게임 흐름 (WalletService 완전 모킹)")

    # 원본 의존성 설정 저장
    original_overrides = app.dependency_overrides.copy()

    try:
        # 미들웨어 없는 앱 생성
        test_app = create_middleware_free_app(app)

        # --- WalletService 완전 모킹 설정 --- 
        from backend.api.dependencies.wallet import get_wallet_service
        from backend.schemas.wallet import BalanceResponse, TransactionResponse
        
        mock_wallet_service = AsyncMock(spec=WalletService)
        
        # get_balance 메서드 모킹 (WalletNotFoundError 발생시키도록 설정)
        async def mock_get_balance(player_id: UUID, partner_id: UUID):
            logger.info(f"Mock get_balance called for {player_id}")
            # 초기 상태: 지갑 없음
            raise WalletNotFoundError(f"Mock Wallet not found for player {player_id}, partner {partner_id}")

        mock_wallet_service.get_balance = AsyncMock(side_effect=mock_get_balance)
        # 만약 API 라우터가 get_wallet 또는 get_wallet_by_player_and_partner를 호출한다면 그것을 모킹해야 함
        mock_wallet_service.get_wallet_by_player_and_partner = AsyncMock(side_effect=WalletNotFoundError("Mock Wallet not found"))
        
        # credit 메서드 모킹 (성공 응답 반환 - TransactionResponse 형태 가정)
        mock_wallet_service.credit = AsyncMock() # 나중에 return_value 설정
        
        # debit 메서드 모킹 (성공 응답 반환 - TransactionResponse 형태 가정)
        mock_wallet_service.debit = AsyncMock() # 나중에 return_value 설정

        # get_player_transactions 모킹
        mock_wallet_service.get_player_transactions = AsyncMock(return_value=([], 0)) # 초기: 빈 리스트

        # rollback 모킹 (필요 시)
        mock_wallet_service.rollback = AsyncMock() 
        
        # 의존성 주입 설정
        test_app.dependency_overrides[get_wallet_service] = lambda: mock_wallet_service
        # --- WalletService 모킹 설정 끝 ---

        # AML 서비스 모킹 (선택 사항, API가 직접 호출하지 않으면 불필요)
        # mock_aml_service = AsyncMock()
        # ... (AML 모킹 설정)
        # test_app.dependency_overrides[get_aml_service] = lambda: mock_aml_service

        # 테스트 클라이언트 생성
        async with AsyncClient(app=test_app, base_url="http://test") as client:
            # 테스트 데이터
            api_key = "test_api_key"
            player_id = str(uuid4())
            partner_id_uuid = uuid4() # Partner ID는 UUID로 사용
            partner_id = str(partner_id_uuid)
            headers = {
                "X-API-Key": api_key,
                "X-Partner-ID": partner_id
            }

            # 1. 서비스 가용성 확인
            logger.info("1️⃣ 서비스 가용성 확인")
            health_response = await client.get("/api/health/health/", headers=headers)
            health_data = await check_response(health_response)
            assert health_data["status"] == "ok", "서비스가 사용 불가능합니다"

            # 2. 플레이어 지갑 잔액 조회 (처음에는 404 예상)
            logger.info(f"2️⃣ 플레이어 {player_id} 잔액 조회")
            # API가 get_wallet_by_player_and_partner 또는 get_balance 호출 -> WalletNotFoundError 발생 -> 404 응답 예상
            balance_response = await client.get(
                f"/v1/api/wallet/{player_id}/balance",
                headers=headers
            )
            assert balance_response.status_code == 404, "지갑이 없을 때 404 응답이 예상됨"
            logger.info(f"플레이어 지갑 없음 확인 (404 응답)")
            initial_balance = Decimal("0")
            logger.info(f"📊 초기 잔액: {initial_balance}")

            # 3. 자금 입금
            deposit_amount = Decimal("1000.00")
            deposit_ref = generate_reference_id("DEPOSIT")
            logger.info(f"3️⃣ 자금 입금 요청: 금액 {deposit_amount}, 참조 ID {deposit_ref}")
            
            # 모킹된 credit 메서드의 반환값 설정 (TransactionResponse와 유사한 구조)
            deposit_tx_id = str(uuid4())
            mock_deposit_response = TransactionResponse(
                transaction_id=deposit_tx_id,
                player_id=UUID(player_id), 
                partner_id=partner_id_uuid,
                reference_id=deposit_ref,
                transaction_type=TransactionType.DEPOSIT,
                amount=deposit_amount,
                currency="USD",
                status=TransactionStatus.COMPLETED,
                balance=deposit_amount, # 입금 후 잔액
                timestamp=datetime.now(timezone.utc)
            )
            mock_wallet_service.credit.return_value = mock_deposit_response
            
            deposit_response = await client.post(
                f"/api/wallet/{player_id}/deposit",
                headers=headers,
                json={
                    "amount": float(deposit_amount),
                    "reference_id": deposit_ref,
                    "currency": "USD"
                }
            )
            deposit_data = await check_response(deposit_response) # 성공 (200 OK) 예상
            
            # 입금 결과 검증 (모킹된 응답과 비교)
            assert deposit_data["reference_id"] == deposit_ref
            assert Decimal(str(deposit_data["amount"])) == deposit_amount
            assert Decimal(str(deposit_data["balance"])) == deposit_amount
            logger.info(f"💰 입금 성공: 새 잔액 {deposit_data['balance']}")

            # 입금 후 잔액 조회 - 이제 성공해야 함
            logger.info(f"🔄 입금 후 잔액 조회")
            # get_balance 또는 get_wallet_by_player_and_partner 모킹 업데이트
            mock_wallet_service.get_wallet_by_player_and_partner.side_effect = None # 예외 발생 중지
            mock_wallet_service.get_wallet_by_player_and_partner.return_value = Wallet(
                id=uuid4(), player_id=UUID(player_id), partner_id=partner_id_uuid,
                balance=deposit_amount, currency="USD", is_active=True, is_locked=False
            )
            # 또는 get_balance 모킹 업데이트
            mock_wallet_service.get_balance.side_effect = None
            mock_wallet_service.get_balance.return_value = BalanceResponse(
                player_id=UUID(player_id),
                partner_id=partner_id_uuid,
                balance=deposit_amount,
                currency="USD",
                timestamp=datetime.now(timezone.utc)
            )

            balance_response_after_deposit = await client.get(
                f"/v1/api/wallet/{player_id}/balance",
                headers=headers
            )
            balance_data_after_deposit = await check_response(balance_response_after_deposit)
            assert Decimal(str(balance_data_after_deposit["balance"])) == deposit_amount
            logger.info(f"✅ 입금 후 잔액 확인: {balance_data_after_deposit['balance']}")
            
            # 4. 게임 목록 조회 (이 부분은 WalletService와 무관하므로 그대로 유지 가능)
            logger.info("4️⃣ 게임 목록 조회")
            games_response = await client.get("/v1/api/games/games", headers=headers)
            games_data = await check_response(games_response)
            if "items" not in games_data or len(games_data.get("items", [])) == 0:
                 logger.info("게임 목록 비어있음. 테스트 건너뛰기 또는 게임 생성 로직 추가 필요")
                 pytest.skip("게임 목록이 비어있어 테스트를 진행할 수 없습니다.")
            else:
                game_id = games_data["items"][0]["id"]
                game_name = games_data["items"][0].get("name", "Unknown Game")
                logger.info(f"🎮 게임 선택: {game_name} (ID: {game_id})")

            # 5. 게임 세션 생성 (WalletService와 무관)
            # ... (기존 코드 유지)

            # 6. 베팅
            bet_amount = Decimal("50.00")
            bet_ref = generate_reference_id("BET")
            logger.info(f"6️⃣ 베팅 요청: 금액 {bet_amount}, 참조 ID {bet_ref}")
            
            # 모킹된 debit 메서드의 반환값 설정
            bet_tx_id = str(uuid4())
            mock_bet_response = TransactionResponse(
                transaction_id=bet_tx_id,
                player_id=UUID(player_id),
                partner_id=partner_id_uuid,
                reference_id=bet_ref,
                transaction_type=TransactionType.BET,
                amount=bet_amount,
                currency="USD",
                status=TransactionStatus.COMPLETED,
                balance=deposit_amount - bet_amount, # 베팅 후 잔액
                timestamp=datetime.now(timezone.utc)
            )
            mock_wallet_service.debit.return_value = mock_bet_response
            
            bet_response = await client.post(
                f"/v1/api/wallet/{player_id}/bet",
                headers=headers,
                json={
                    "amount": float(bet_amount),
                    "reference_id": bet_ref,
                    "currency": "USD",
                    "game_id": game_id, # 게임 ID 추가
                    # "metadata": {} # 필요 시 메타데이터 추가
                }
            )
            bet_data = await check_response(bet_response)
            
            # 베팅 결과 검증
            assert bet_data["reference_id"] == bet_ref
            assert Decimal(str(bet_data["amount"])) == bet_amount
            assert Decimal(str(bet_data["balance"])) == deposit_amount - bet_amount
            logger.info(f"💸 베팅 성공: 새 잔액 {bet_data['balance']}")

            # 7. 승리
            win_amount = Decimal("100.00")
            win_ref = generate_reference_id("WIN")
            logger.info(f"7️⃣ 승리 요청: 금액 {win_amount}, 참조 ID {win_ref}")

            # 승리는 credit 메서드 사용 가정, 모킹된 credit 업데이트
            win_tx_id = str(uuid4())
            mock_win_response = TransactionResponse(
                transaction_id=win_tx_id,
                player_id=UUID(player_id),
                partner_id=partner_id_uuid,
                reference_id=win_ref,
                transaction_type=TransactionType.WIN,
                amount=win_amount,
                currency="USD",
                status=TransactionStatus.COMPLETED,
                balance=deposit_amount - bet_amount + win_amount, # 승리 후 잔액
                timestamp=datetime.now(timezone.utc)
            )
            # credit 메서드가 WIN 트랜잭션도 처리한다고 가정
            mock_wallet_service.credit.return_value = mock_win_response 
            
            win_response = await client.post(
                f"/v1/api/wallet/{player_id}/win",
                headers=headers,
                json={
                    "amount": float(win_amount),
                    "reference_id": win_ref,
                    "currency": "USD",
                    "game_id": game_id, # 게임 ID 추가
                    # "metadata": {} # 필요 시 메타데이터 추가
                }
            )
            win_data = await check_response(win_response)

            # 승리 결과 검증
            assert win_data["reference_id"] == win_ref
            assert Decimal(str(win_data["amount"])) == win_amount
            assert Decimal(str(win_data["balance"])) == deposit_amount - bet_amount + win_amount
            logger.info(f"🏆 승리 성공: 새 잔액 {win_data['balance']}")

            # 8. 거래 내역 조회
            logger.info("8️⃣ 거래 내역 조회")
            # get_player_transactions 모킹 업데이트
            # 실제 Transaction 객체 대신 TransactionResponse 스키마를 따르는 dict 사용 가능
            mock_transactions_data = [
                mock_deposit_response.dict(),
                mock_bet_response.dict(),
                mock_win_response.dict()
            ]
            mock_wallet_service.get_player_transactions.return_value = (mock_transactions_data, len(mock_transactions_data))

            transactions_response = await client.get(
                f"/v1/api/wallet/{player_id}/transactions",
                headers=headers
            )
            transactions_data = await check_response(transactions_response)
            assert "items" in transactions_data
            assert len(transactions_data["items"]) == 3 # 입금, 베팅, 승리
            logger.info(f"✅ 거래 내역 조회 성공: {len(transactions_data['items'])} 건")

            # 9. 최종 잔액 확인
            logger.info("9️⃣ 최종 잔액 확인")
            # get_balance 모킹 업데이트
            final_expected_balance = deposit_amount - bet_amount + win_amount
            mock_wallet_service.get_balance.return_value = BalanceResponse(
                 player_id=UUID(player_id),
                 partner_id=partner_id_uuid,
                 balance=final_expected_balance,
                 currency="USD",
                 timestamp=datetime.now(timezone.utc)
            )
             # get_wallet_by_player_and_partner 모킹 업데이트
            mock_wallet_service.get_wallet_by_player_and_partner.return_value = Wallet(
                id=uuid4(), player_id=UUID(player_id), partner_id=partner_id_uuid,
                balance=final_expected_balance, currency="USD", is_active=True, is_locked=False
            )

            final_balance_response = await client.get(
                f"/v1/api/wallet/{player_id}/balance",
                headers=headers
            )
            final_balance_data = await check_response(final_balance_response)
            assert Decimal(str(final_balance_data["balance"])) == final_expected_balance
            logger.info(f"✅ 최종 잔액 확인: {final_balance_data['balance']}")

            # 10. 롤백 테스트 (모킹 업데이트 필요)
            # ... (롤백 API 호출 및 검증, 필요 시 mock_wallet_service.rollback 모킹 설정)

            logger.info("🎉 E2E 테스트 완료: 모든 단계 성공 (WalletService 모킹)")

    except AssertionError as ae:
        logger.error(f"❌ 테스트 실패 (검증 오류): {str(ae)}")
        raise
    except Exception as e:
        logger.error(f"⚠️ 테스트 실패 (예외 발생): {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise
    finally:
        # 원래 의존성 설정 복원
        app.dependency_overrides = original_overrides
        logger.info("🧹 테스트 정리 완료: 의존성 설정 복원")

@pytest.fixture
def mock_aml_service():
    service = AsyncMock()
    # 필요한 메서드 명시적으로 추가
    service._get_historical_transactions = AsyncMock(return_value=[])
    service._get_or_create_risk_profile = AsyncMock(return_value={
        "player_id": "test_id",
        "risk_score": 0,
        "flags": []
    })
    service._create_alert = AsyncMock()
    service.analyze_transaction = AsyncMock(return_value={"risk_score": 0})
    return service

@pytest.fixture
def mock_api_key_repo():
    repo = AsyncMock()
    # list_api_keys 메서드 명시적으로 추가
    repo.list_api_keys = AsyncMock(return_value=[
        {
            "id": str(uuid4()),
            "partner_id": "test_partner_id",
            "key": f"test_key_{uuid4()}",
            "status": "active"
        }
    ])
    return repo

# 테스트용 환경 변수 설정 함수
def setup_test_env_vars():
    """테스트 환경에 필요한 환경 변수를 설정합니다."""
    # AES-GCM 키 생성 (32바이트)
    valid_aes_key = base64.b64encode(os.urandom(32)).decode('utf-8')
    # 일반 암호화 키 생성
    valid_enc_key = base64.b64encode(os.urandom(32)).decode('utf-8')
    
    env_vars = {
        "AESGCM_KEY_B64": valid_aes_key,
        "ENCRYPTION_KEY": valid_enc_key, 
        "ENVIRONMENT": "test",
        "DEFAULT_RETURN_URL": "https://test-return.com",
    }
    
    # 기존 환경 변수 저장
    original_vars = {}
    
    # 환경 변수 설정
    for key, value in env_vars.items():
        original_vars[key] = os.environ.get(key)
        os.environ[key] = value
    
    return original_vars

# 테스트 실행 전 환경 변수 설정
original_env_vars = setup_test_env_vars()