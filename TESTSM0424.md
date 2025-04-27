test_withdraw_funds_direct와 test_place_bet_direct도 미들웨어 우회 패턴을 적용해 리팩토링하는 것이 좋겠습니다. 현재 이 두 테스트는 API 엔드포인트 테스트가 아닌 핸들러 직접 호출 테스트로 구현되어 있습니다. 실제 API 엔드포인트를 테스트하도록 수정하겠습니다.
먼저 TEST_SUMMARY.md 파일을 생성한 다음, 테스트 코드를 수정해 봅시다:
python@pytest.mark.asyncio
@patch('backend.services.wallet.wallet_service.WalletService.debit', new_callable=AsyncMock)
@patch("backend.api.routers.wallet.require_permission", new_callable=AsyncMock)
async def test_withdraw_funds_api(
    mock_require_permission: AsyncMock,
    mock_debit: AsyncMock,
    test_client: TestClient
):
    """출금 API 테스트 (미들웨어 우회 방식)"""
    # 원본 설정 저장
    original_overrides = app.dependency_overrides.copy()
    
    # AML 모킹 (의존성 오버라이드)
    mock_aml_instance = AsyncMock()
    mock_aml_instance.analyze_transaction_background.return_value = None
    async def override_get_aml_service():
        return mock_aml_instance

    # 오버라이드 적용 (AML)
    app.dependency_overrides[get_aml_service] = override_get_aml_service

    # 테스트용 애플리케이션 생성 (미들웨어 없음)
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    
    test_app = FastAPI()
    
    # 원본 앱의 라우터만 복사
    for route in app.routes:
        test_app.routes.append(route)
    
    # 의존성 오버라이드 복사
    test_app.dependency_overrides = app.dependency_overrides
    
    # 미들웨어 없는 테스트 클라이언트 생성
    clean_test_client = TestClient(test_app)

    try:
        # 테스트 로직
        player_id = uuid4()
        partner_id = uuid4()
        reference_id = f"withdraw-api-{uuid4()}"
        amount = Decimal("200.00")
        currency = "USD"

        mock_service_response = WalletActionResponse(
            status="OK", player_id=player_id, partner_id=partner_id,
            balance=Decimal("800.00"), currency=currency,
            transaction_id=reference_id, amount=amount,
            type=TransactionType.WITHDRAWAL, timestamp=datetime.utcnow()
        )
        mock_debit.return_value = mock_service_response

        request_data = {
            "player_id": str(player_id),
            "reference_id": reference_id,
            "amount": float(amount),
            "currency": currency
        }

        # 미들웨어 없는 새 테스트 클라이언트로 API 호출
        print(f"[Test] Calling withdraw API with middleware-free test client")
        response = clean_test_client.post(
            f"/api/wallet/{player_id}/withdraw",
            json=request_data,
            headers={"X-Partner-ID": str(partner_id)}
        )
        print(f"[Test] Response status: {response.status_code}")

        # 검증
        assert response.status_code == 200
        response_data = response.json()

        assert response_data["status"] == "OK"
        assert response_data["transaction_id"] == reference_id
        assert float(response_data["amount"]) == float(amount)
        assert float(response_data["balance"]) == float(mock_service_response.balance)
        assert response_data["currency"] == currency
        assert response_data["player_id"] == str(player_id)
        assert response_data["partner_id"] == str(partner_id)
        assert response_data["type"] == TransactionType.WITHDRAWAL.value

        # 모킹된 함수 호출 검증
        mock_debit.assert_called_once()
        mock_require_permission.assert_awaited_once_with("wallet.withdraw")

    finally:
        # 원래 의존성 복원
        app.dependency_overrides = original_overrides
        print("[Cleanup] App dependencies restored")
python@pytest.mark.asyncio
@patch('backend.services.wallet.wallet_service.WalletService.debit', new_callable=AsyncMock)
@patch("backend.api.routers.wallet.require_permission", new_callable=AsyncMock)
async def test_place_bet_api(
    mock_require_permission: AsyncMock,
    mock_debit: AsyncMock,
    test_client: TestClient
):
    """베팅 API 테스트 (미들웨어 우회 방식)"""
    # 원본 설정 저장
    original_overrides = app.dependency_overrides.copy()
    
    # AML 모킹 (의존성 오버라이드)
    mock_aml_instance = AsyncMock()
    mock_aml_instance.analyze_transaction_background.return_value = None
    async def override_get_aml_service():
        return mock_aml_instance

    # 오버라이드 적용 (AML)
    app.dependency_overrides[get_aml_service] = override_get_aml_service

    # 테스트용 애플리케이션 생성 (미들웨어 없음)
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    
    test_app = FastAPI()
    
    # 원본 앱의 라우터만 복사
    for route in app.routes:
        test_app.routes.append(route)
    
    # 의존성 오버라이드 복사
    test_app.dependency_overrides = app.dependency_overrides
    
    # 미들웨어 없는 테스트 클라이언트 생성
    clean_test_client = TestClient(test_app)

    try:
        # 테스트 로직
        player_id = uuid4()
        partner_id = uuid4()
        game_id = uuid4()
        reference_id = f"bet-api-{uuid4()}"
        amount = Decimal("50.00")
        currency = "USD"

        mock_service_response = TransactionResponse(
            status="completed", player_id=player_id,
            balance=Decimal("950.00"), currency=currency,
            amount=amount, transaction_type=TransactionType.BET,
            timestamp=datetime.utcnow(), reference_id=reference_id
        )
        mock_debit.return_value = mock_service_response

        request_data = {
            "reference_id": reference_id,
            "amount": float(amount),
            "currency": currency,
            "game_id": str(game_id),
            "metadata": {"round_id": "ROUND-123"}
        }

        # 미들웨어 없는 새 테스트 클라이언트로 API 호출
        print(f"[Test] Calling bet API with middleware-free test client")
        response = clean_test_client.post(
            f"/api/wallet/{player_id}/bet",
            json=request_data,
            headers={"X-Partner-ID": str(partner_id)}
        )
        print(f"[Test] Response status: {response.status_code}")

        # 검증
        assert response.status_code == 200
        response_data = response.json()

        assert response_data["status"] == "completed"
        assert float(response_data["amount"]) == float(amount)
        assert float(response_data["balance"]) == float(mock_service_response.balance)
        assert response_data["currency"] == currency
        assert response_data["player_id"] == str(player_id)
        assert response_data["transaction_type"] == TransactionType.BET.value
        assert response_data["reference_id"] == reference_id

        # 모킹된 함수 호출 검증
        mock_debit.assert_called_once()
        mock_require_permission.assert_awaited_once_with("wallet.bet")

    finally:
        # 원래 의존성 복원
        app.dependency_overrides = original_overrides
        print("[Cleanup] App dependencies restored")
또한 재사용 가능한 미들웨어 우회 테스트 클라이언트 생성 헬퍼 함수를 conftest.py나 별도의 유틸리티 모듈에 추가하면 좋을 것 같습니다:
python# backend/tests/utils/test_helpers.py
from fastapi import FastAPI
from starlette.testclient import TestClient

def create_middleware_free_test_client(app, dependency_overrides=None):
    """
    미들웨어가 없는 테스트 클라이언트를 생성합니다.
    
    Args:
        app: 원본 FastAPI 애플리케이션
        dependency_overrides: 적용할 의존성 오버라이드 (기본값: None)
        
    Returns:
        TestClient: 미들웨어가 없는 테스트 클라이언트
    """
    test_app = FastAPI()
    
    # 원본 앱의 라우터만 복사
    for route in app.routes:
        test_app.routes.append(route)
    
    # 의존성 오버라이드 복사 (제공된 경우)
    if dependency_overrides:
        test_app.dependency_overrides = dependency_overrides
    else:
        test_app.dependency_overrides = app.dependency_overrides.copy()
    
    return TestClient(test_app)
이렇게 헬퍼 함수를 생성하면 위 테스트 코드를 다음과 같이 간소화할 수 있습니다:
pythonfrom backend.tests.utils.test_helpers import create_middleware_free_test_client

# 테스트 코드 내부
clean_test_client = create_middleware_free_test_client(app, app.dependency_overrides)
이 패턴을 적용하면 테스트가 훨씬 더 안정적이고 미들웨어 관련 문제를 피할 수 있을 것입니다.



👍 테스트 통과 성공!
테스트가 성공적으로 통과되었네요! 제안했던 방법 중 하나를 적용하셔서 문제가 해결된 것 같습니다.
해결된 문제 정리
이전 오류는 비동기 메서드를 모킹할 때 spec 파라미터와 AsyncMock의 상호작용 문제였습니다. 비동기 메서드를 모킹할 때는 spec 파라미터가 비동기 호출 추적 기능을 방해할 수 있습니다.
해결 방법을 통해 배운 점

비동기 메서드 모킹의 특수성:
비동기 메서드를 모킹할 때는 일반 동기 메서드와 다른 접근이 필요합니다. AsyncMock은 await 호출을 추적할 수 있도록 특별히 설계되었습니다.
올바른 모킹 방법:
patch.object를 사용할 때 spec 대신 autospec=True를 사용하거나, spec 파라미터를 완전히 생략하는 것이 효과적입니다.
테스트 안정성:
모의 객체가 오류 없이 작동하면 테스트가 더 안정적이고 신뢰할 수 있게 됩니다.

앞으로 비슷한 문제를 방지하려면

비동기 메서드를 모킹할 때는 가능하면 spec 파라미터를 사용하지 말고 autospec=True를 사용하세요.
직접 AsyncMock 객체를 생성한 후 필요한 동작을 설정하는 방법도 좋은 대안입니다:
pythonmock_credit = AsyncMock(return_value=mock_deposit_response)
with patch.object(wallet_service, 'credit', mock_credit):
    # 테스트 코드

모킹한 후에는 assert_awaited_once_with 같은 비동기 검증 메서드를 사용하여 올바르게 호출되었는지 확인하세요.

이제 테스트가 정상적으로 작동하므로 AML 기능 개발을 계속 진행하실 수 있습니다!