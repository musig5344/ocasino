# tests/integration/test_wallet_api.py
import pytest
import uuid
from decimal import Decimal
from httpx import AsyncClient
from unittest.mock import AsyncMock
from backend.main import app as main_app
# Use TestClient if that's what the fixture provides
# from httpx import AsyncClient 
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

# Import necessary models and helpers
from backend.models.domain.wallet import Wallet, TransactionType, TransactionStatus
from backend.schemas.wallet import TransactionRequest, WalletActionResponse
# from tests.conftest import create_test_wallet # Import the helper from conftest

@pytest.mark.asyncio
async def test_credit_wallet_api(test_client: AsyncClient, test_partner, test_player):
    """Test the POST /api/wallet/{player_id}/deposit endpoint for depositing funds."""
    partner = await test_partner
    player = await test_player # UUID 반환 가정
    
    partner_id = partner.id 
    player_id = player 
    
    currency = "USD"
    amount = Decimal("500.00")
    reference_id = f"INTEGRATION-DEPOSIT-{uuid.uuid4()}" # deposit으로 변경

    # TransactionRequest 스키마에 맞는 payload 생성
    payload = TransactionRequest(
        reference_id=reference_id,
        amount=amount, 
        currency=currency,
        # metadata 필요 시 추가
        # metadata={"reason": "Integration test deposit"}
    ).dict()

    # 올바른 API 경로 사용
    api_path = f"/api/wallet/{player_id}/deposit"
    print(f"\nSending deposit request to API: {api_path} with payload: {payload}")
    
    # test_client 픽스처에서 헤더(API 키 등)가 설정되었다고 가정
    response = await test_client.post(api_path, json=payload)

    # Assertions
    print(f"Deposit Response Status: {response.status_code}")
    print(f"Deposit Response Body: {response.text}")
    
    # API 성공 응답 코드 확인 (deposit_funds는 WalletActionResponse 반환)
    assert response.status_code == status.HTTP_200_OK 
    response_data = response.json()

    # WalletActionResponse 스키마에 맞춰 검증
    assert response_data["status"] == "OK" # WalletActionResponse의 status 필드
    assert response_data["transaction_id"] is not None # 트랜잭션 ID 존재 여부
    assert response_data["player_id"] == str(player_id)
    assert response_data["partner_id"] == str(partner_id)
    assert Decimal(str(response_data["amount"])) == amount # amount 필드 확인
    assert response_data["type"] == TransactionType.DEPOSIT.value # type 필드 확인
    # 잔액 검증은 초기 잔액을 알아야 하므로, 별도 API 호출 또는 다른 방식으로 확인 필요
    # assert Decimal(str(response_data["balance"])) == initial_balance + amount
    
    print("Deposit API test completed successfully.")

# Add more integration tests for other Wallet API endpoints:
# - /v1/wallets/debit (placing a bet)
# - /v1/wallets/rollback
# - /v1/wallets/{player_id}/balance
# - /v1/wallets/{player_id}/transactions

# Add more integration tests for debit, bet, win, balance check, error cases, etc. 