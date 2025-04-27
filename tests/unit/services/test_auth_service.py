import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
from uuid import uuid4

from backend.services.auth.auth_service import AuthService
from backend.partners.models import Partner, ApiKey
from backend.core.exceptions import AuthenticationError, NotAllowedIPError

@pytest.fixture
def mock_db_session():
    db = AsyncMock()
    db.flush = AsyncMock()
    return db

@pytest.fixture
def mock_partner_repo():
    return AsyncMock()

@pytest.fixture
def mock_redis_client():
    return AsyncMock()

@pytest.fixture
def auth_service(mock_db_session, mock_partner_repo, mock_redis_client):
    """인증 서비스 인스턴스 생성 (mocked dependencies)"""
    # Pass mocks to the constructor
    service = AuthService(db=mock_db_session, redis_client=mock_redis_client)
    # Assign mocked repo manually (if needed, depends on AuthService.__init__)
    service.partner_repo = mock_partner_repo
    # Assign mocked redis manually if constructor doesn't take it (unlikely based on other files)
    # service.redis = mock_redis_client 
    
    return service

@pytest.mark.asyncio
async def test_authenticate_api_key_valid(auth_service):
    """유효한 API 키 인증 테스트"""
    # 테스트 데이터 준비
    api_key = "test_api_key"
    api_key_hash = "hashed_key"
    
    # mock 리턴 값 설정
    api_key_obj = ApiKey(
        id=uuid4(),
        partner_id=uuid4(),
        key=api_key_hash,
        name="Test Key",
        permissions=["wallet:read", "wallet:write"],
        is_active=True,
        expires_at=datetime.utcnow() + timedelta(days=30)
    )
    
    partner = Partner(
        id=api_key_obj.partner_id,
        code="test_partner",
        name="Test Partner",
        status="active"
    )
    
    # 레디스 캐시 미스 시뮬레이션
    auth_service.redis.get.return_value = None
    
    # 리포지토리 모의 응답 설정
    auth_service.partner_repo.get_active_api_key_by_hash.return_value = api_key_obj
    auth_service.partner_repo.get_partner_by_id.return_value = partner
    
    # hash_api_key 함수 패치 (경로 수정 가능성)
    with patch('backend.services.auth.auth_service.get_password_hash', return_value=api_key_hash):
        # 테스트 대상 함수 호출
        result_api_key, result_partner = await auth_service.authenticate_api_key(api_key)
        
        # 결과 검증
        assert result_api_key == api_key_obj
        assert result_partner == partner
        auth_service.partner_repo.get_active_api_key_by_hash.assert_called_with(api_key_hash)
        auth_service.partner_repo.get_partner_by_id.assert_called_with(api_key_obj.partner_id)
        auth_service.redis.set.assert_called_once()  # 캐시 저장 호출 확인

@pytest.mark.asyncio
async def test_authenticate_api_key_expired(auth_service):
    """만료된 API 키 인증 테스트"""
    # 테스트 데이터 준비
    api_key = "test_api_key"
    api_key_hash = "hashed_key"
    
    # 만료된 API 키 객체 생성
    api_key_obj = ApiKey(
        id=uuid4(),
        partner_id=uuid4(),
        key=api_key_hash,
        name="Test Key",
        permissions=["wallet:read"],
        is_active=True,
        expires_at=datetime.utcnow() - timedelta(days=1)  # 이미 만료됨
    )
    
    # 레디스 캐시 미스 시뮬레이션
    auth_service.redis.get.return_value = None
    
    # 리포지토리 모의 응답 설정
    auth_service.partner_repo.get_active_api_key_by_hash.return_value = api_key_obj
    
    # hash_api_key 함수 패치 (경로 확인 필요, 여기서는 get_password_hash 사용 가정)
    # Use the same target as in the other test file for consistency
    with patch('backend.core.security.get_password_hash', return_value=api_key_hash):
        # 예외 발생 확인
        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.authenticate_api_key(api_key)
        
        # 예외 메시지 검증 (부분 문자열 검증으로 변경)
        assert "has expired" in str(exc_info.value) # Corrected assertion

@pytest.mark.asyncio
async def test_verify_ip_whitelist_allowed(auth_service):
    """허용된 IP 주소 확인 테스트"""
    # 테스트 데이터 준비
    partner_id = uuid4()
    client_ip = "192.168.1.1"
    
    # 허용된 IP 목록 설정
    allowed_ips = [
        MagicMock(ip_address=client_ip)
    ]
    
    # 리포지토리 모의 응답 설정
    auth_service.partner_repo.get_allowed_ips.return_value = allowed_ips
    
    # 테스트 대상 함수 호출
    result = await auth_service.verify_ip_whitelist(partner_id, client_ip)
    
    # 결과 검증
    assert result is True
    auth_service.partner_repo.get_allowed_ips.assert_called_with(partner_id)

@pytest.mark.asyncio
async def test_verify_ip_whitelist_not_allowed(auth_service):
    """허용되지 않은 IP 주소 확인 테스트"""
    # 테스트 데이터 준비
    partner_id = uuid4()
    client_ip = "192.168.1.2"
    
    # 허용된 IP 목록 설정 (테스트 IP는 포함되지 않음)
    allowed_ips = [
        MagicMock(ip_address="192.168.1.1")
    ]
    
    # 리포지토리 모의 응답 설정
    auth_service.partner_repo.get_allowed_ips.return_value = allowed_ips
    
    # 예외 발생 확인
    with pytest.raises(NotAllowedIPError) as exc_info:
        await auth_service.verify_ip_whitelist(partner_id, client_ip)
    
    # 예외 메시지 검증
    assert client_ip in str(exc_info.value)
    assert str(partner_id) in str(exc_info.value)