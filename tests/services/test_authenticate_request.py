"""
API 요청 인증 및 권한 확인 테스트
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4
from fastapi import HTTPException, status

# 필요한 예외 클래스 정의
class AuthenticationError(Exception):
    """인증 실패 시 발생하는 예외"""
    pass

class NotAllowedIPError(Exception):
    """허용되지 않은 IP 접근 시 발생하는 예외"""
    pass

class PermissionDeniedError(Exception):
    """권한이 없는 경우 발생하는 예외"""
    pass

# 테스트할 함수 정의
async def authenticate_request(request, required_permission=None, auth_service=None):
    """
    요청 인증 및 권한 확인 함수 (AuthService에서 분리)
    
    Args:
        request: HTTP 요청 객체
        required_permission: 필요한 권한 (선택)
        auth_service: 인증 서비스 객체 (모킹용)
            
    Returns:
        tuple: (API 키 객체, 파트너 객체)
            
    Raises:
        HTTPException: 인증 또는 권한 확인 실패 시
    """
    # API 키 추출
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key missing"
        )
    
    try:
        # API 키 인증
        # Ensure auth_service is provided
        if auth_service is None:
             raise ValueError("auth_service must be provided for testing")
             
        api_key_obj, partner = await auth_service.authenticate_api_key(api_key)
        
        # IP 화이트리스트 확인
        # Ensure request.client and request.client.host exist
        client_ip = getattr(getattr(request, 'client', None), 'host', None)
        if client_ip is None:
             # Handle cases where client IP cannot be determined (e.g., test setup)
             # Depending on policy, either raise an error or allow if IP check is not strictly needed
             # For now, let's assume it should be present for IP check
             raise HTTPException(
                 status_code=status.HTTP_400_BAD_REQUEST, 
                 detail="Could not determine client IP address"
             )
             
        await auth_service.verify_ip_whitelist(partner.id, client_ip)
        
        # 권한 확인 (필요한 경우)
        if required_permission:
            await auth_service.check_permission(api_key_obj, required_permission)
        
        return api_key_obj, partner
    
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except NotAllowedIPError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except PermissionDeniedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    # Catch potential ValueErrors from checks above
    except ValueError as e: 
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Internal configuration error: {e}"
        )


# 테스트 케이스
@pytest.mark.asyncio
async def test_authenticate_request_success():
    """API 요청 인증 성공 테스트"""
    # 모의 요청 객체
    request = MagicMock()
    request.headers = {"X-API-Key": "test_api_key"}
    request.client = MagicMock()
    request.client.host = "192.168.1.1"
    
    # 모의 API 키와 파트너 객체
    api_key_obj = MagicMock()
    api_key_obj.id = uuid4()
    api_key_obj.permissions = ["*"]
    
    partner = MagicMock()
    partner.id = uuid4()
    
    # 모의 인증 서비스
    auth_service = AsyncMock()
    auth_service.authenticate_api_key.return_value = (api_key_obj, partner)
    # Ensure side effects are cleared if reusing mocks, or use new mocks
    auth_service.verify_ip_whitelist.side_effect = None 
    auth_service.verify_ip_whitelist.return_value = True
    auth_service.check_permission.side_effect = None
    auth_service.check_permission.return_value = True
    
    # 함수 호출
    result_api_key, result_partner = await authenticate_request(
        request, 
        required_permission="wallet:read",
        auth_service=auth_service
    )
    
    # 검증
    assert result_api_key == api_key_obj
    assert result_partner == partner
    
    # 호출 검증
    auth_service.authenticate_api_key.assert_called_once_with("test_api_key")
    auth_service.verify_ip_whitelist.assert_called_once_with(partner.id, "192.168.1.1")
    auth_service.check_permission.assert_called_once_with(api_key_obj, "wallet:read")

@pytest.mark.asyncio
async def test_authenticate_request_success_no_permission_required():
    """API 요청 인증 성공 테스트 - 권한 필요 없음"""
    request = MagicMock()
    request.headers = {"X-API-Key": "test_api_key"}
    request.client = MagicMock()
    request.client.host = "192.168.1.1"
    
    api_key_obj = MagicMock()
    partner = MagicMock()
    partner.id = uuid4()
    
    auth_service = AsyncMock()
    auth_service.authenticate_api_key.return_value = (api_key_obj, partner)
    auth_service.verify_ip_whitelist.return_value = True
    
    result_api_key, result_partner = await authenticate_request(
        request, 
        required_permission=None, # No permission required
        auth_service=auth_service
    )
    
    assert result_api_key == api_key_obj
    assert result_partner == partner
    auth_service.authenticate_api_key.assert_called_once_with("test_api_key")
    auth_service.verify_ip_whitelist.assert_called_once_with(partner.id, "192.168.1.1")
    auth_service.check_permission.assert_not_called() # 권한 확인 안 함

@pytest.mark.asyncio
async def test_authenticate_request_missing_api_key():
    """API 키 누락 테스트"""
    # 모의 요청 객체 (API 키 없음)
    request = MagicMock()
    request.headers = {}
    # Ensure client attribute exists even if not used here
    request.client = MagicMock()
    request.client.host = "192.168.1.1" 
    
    # 모의 인증 서비스
    auth_service = AsyncMock()
    
    # 함수 호출 및 예외 확인
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_request(request, auth_service=auth_service)
    
    # 예외 검증
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "API key missing" in exc_info.value.detail
    
    # 서비스 메소드 호출되지 않음 검증
    auth_service.authenticate_api_key.assert_not_called()

@pytest.mark.asyncio
async def test_authenticate_request_authentication_error():
    """인증 실패 테스트"""
    # 모의 요청 객체
    request = MagicMock()
    request.headers = {"X-API-Key": "invalid_api_key"}
    request.client = MagicMock()
    request.client.host = "192.168.1.1" 
    
    # 모의 인증 서비스 (인증 실패)
    auth_service = AsyncMock()
    auth_service.authenticate_api_key.side_effect = AuthenticationError("Invalid API key")
    
    # 함수 호출 및 예외 확인
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_request(request, auth_service=auth_service)
    
    # 예외 검증
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Invalid API key" in exc_info.value.detail
    
    # 호출 검증
    auth_service.authenticate_api_key.assert_called_once_with("invalid_api_key")
    auth_service.verify_ip_whitelist.assert_not_called()

@pytest.mark.asyncio
async def test_authenticate_request_ip_not_allowed():
    """IP 허용되지 않음 테스트"""
    # 모의 요청 객체
    request = MagicMock()
    request.headers = {"X-API-Key": "test_api_key"}
    request.client = MagicMock()
    request.client.host = "10.0.0.1"
    
    # 모의 API 키와 파트너 객체
    api_key_obj = MagicMock()
    partner = MagicMock()
    partner.id = uuid4()
    
    # 모의 인증 서비스 (IP 허용 안됨)
    auth_service = AsyncMock()
    auth_service.authenticate_api_key.return_value = (api_key_obj, partner)
    auth_service.verify_ip_whitelist.side_effect = NotAllowedIPError("IP not in whitelist")
    
    # 함수 호출 및 예외 확인
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_request(request, auth_service=auth_service)
    
    # 예외 검증
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "IP not in whitelist" in exc_info.value.detail
    
    # 호출 검증
    auth_service.authenticate_api_key.assert_called_once_with("test_api_key")
    auth_service.verify_ip_whitelist.assert_called_once_with(partner.id, "10.0.0.1")
    auth_service.check_permission.assert_not_called()

@pytest.mark.asyncio
async def test_authenticate_request_permission_denied():
    """권한 없음 테스트"""
    # 모의 요청 객체
    request = MagicMock()
    request.headers = {"X-API-Key": "test_api_key"}
    request.client = MagicMock()
    request.client.host = "192.168.1.1"
    
    # 모의 API 키와 파트너 객체
    api_key_obj = MagicMock()
    api_key_obj.permissions = ["game:list"] # 다른 권한 보유
    
    partner = MagicMock()
    partner.id = uuid4()
    
    # 모의 인증 서비스 (권한 없음)
    auth_service = AsyncMock()
    auth_service.authenticate_api_key.return_value = (api_key_obj, partner)
    # Ensure previous side effects are cleared
    auth_service.verify_ip_whitelist.side_effect = None
    auth_service.verify_ip_whitelist.return_value = True 
    auth_service.check_permission.side_effect = PermissionDeniedError("Missing required permission: wallet:read")
    
    # 함수 호출 및 예외 확인
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_request(
            request, 
            required_permission="wallet:read", # 필요한 권한
            auth_service=auth_service
        )
    
    # 예외 검증
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "Missing required permission: wallet:read" in exc_info.value.detail
    
    # 호출 검증
    auth_service.authenticate_api_key.assert_called_once_with("test_api_key")
    auth_service.verify_ip_whitelist.assert_called_once_with(partner.id, "192.168.1.1")
    auth_service.check_permission.assert_called_once_with(api_key_obj, "wallet:read") 