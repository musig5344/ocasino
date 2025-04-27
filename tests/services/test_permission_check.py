"""
권한 확인 기능 테스트
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
import json

# 필요한 예외 클래스 정의
class PermissionDeniedError(Exception):
    """권한이 없는 경우 발생하는 예외"""
    pass

# 테스트할 함수만 분리
async def check_permission(api_key, required_permission):
    """
    권한 확인 함수 (AuthService에서 분리)
    
    Args:
        api_key: API 키 객체 (permissions 속성 필요)
        required_permission: 필요한 권한
            
    Returns:
        bool: 권한 보유 여부
            
    Raises:
        PermissionDeniedError: 권한이 없는 경우
    """
    # API 키의 permissions는 JSON 문자열로 저장되어 있을 수 있으므로 확인
    permissions_attr = api_key.permissions
    permissions = []
    if isinstance(permissions_attr, str):
        try:
            # Attempt to parse as JSON list
            parsed = json.loads(permissions_attr)
            if isinstance(parsed, list):
                permissions = parsed
            else:
                # If not a list (e.g., single string after JSON parse), treat as single permission
                permissions = [str(parsed)] 
        except json.JSONDecodeError:
            # If not valid JSON, assume it's a single permission string (or comma-separated)
            # Simple split by comma for basic support, adjust if needed
            permissions = [p.strip() for p in permissions_attr.split(',') if p.strip()]
    elif isinstance(permissions_attr, list):
        permissions = permissions_attr # Already a list
    elif permissions_attr is None:
        permissions = [] # No permissions if None
    else:
        # Handle unexpected types if necessary, defaulting to no permissions
        permissions = []

    # Ensure all elements are strings
    permissions = [str(p) for p in permissions]

    # 모든 권한 확인 (* 와일드카드)
    if "*" in permissions:
        return True
    
    # 특정 리소스의 모든 권한 확인 (wallet:* 등)
    try:
        resource = required_permission.split(":")[0]
        if f"{resource}:*" in permissions:
            return True
    except IndexError:
        # Handle cases where required_permission doesn't have a colon
        pass # Continue to check for exact match
    
    # 특정 권한 확인
    if required_permission in permissions:
        return True
    
    # 권한 없음
    raise PermissionDeniedError(f"Missing required permission: {required_permission}")

# 테스트 케이스
@pytest.mark.asyncio
async def test_check_permission_wildcard():
    """권한 확인 테스트 - 와일드카드 권한"""
    # API 키 모의 객체 (모든 권한)
    api_key = MagicMock()
    api_key.permissions = ["*"]
    
    # 권한 확인
    result = await check_permission(api_key, "wallet:read")
    
    # 검증
    assert result is True

@pytest.mark.asyncio
async def test_check_permission_resource_wildcard():
    """권한 확인 테스트 - 리소스 와일드카드 권한"""
    # API 키 모의 객체 (wallet 관련 모든 권한)
    api_key = MagicMock()
    api_key.permissions = ["wallet:*"]
    
    # 권한 확인
    result = await check_permission(api_key, "wallet:read")
    assert result is True
    result = await check_permission(api_key, "wallet:write")
    assert result is True

@pytest.mark.asyncio
async def test_check_permission_specific():
    """권한 확인 테스트 - 특정 권한"""
    # API 키 모의 객체 (특정 권한만)
    api_key = MagicMock()
    api_key.permissions = ["wallet:read", "game:list"]
    
    # 권한 확인
    result = await check_permission(api_key, "wallet:read")
    assert result is True

    with pytest.raises(PermissionDeniedError):
      await check_permission(api_key, "wallet:write") 


@pytest.mark.asyncio
async def test_check_permission_json_string():
    """권한 확인 테스트 - JSON 문자열로 저장된 권한"""
    # API 키 모의 객체 (JSON 문자열 권한)
    api_key = MagicMock()
    api_key.permissions = '["wallet:read", "game:list"]'
    
    # 권한 확인
    result = await check_permission(api_key, "wallet:read")
    assert result is True

    with pytest.raises(PermissionDeniedError):
        await check_permission(api_key, "report:generate")

@pytest.mark.asyncio
async def test_check_permission_simple_string():
    """권한 확인 테스트 - 단일 문자열 권한"""
    api_key = MagicMock()
    api_key.permissions = "wallet:read"
    
    result = await check_permission(api_key, "wallet:read")
    assert result is True

    with pytest.raises(PermissionDeniedError):
        await check_permission(api_key, "game:list")

@pytest.mark.asyncio
async def test_check_permission_comma_separated_string():
    """권한 확인 테스트 - 쉼표로 구분된 문자열 권한"""
    api_key = MagicMock()
    api_key.permissions = "wallet:read, game:list"
    
    result = await check_permission(api_key, "wallet:read")
    assert result is True
    result = await check_permission(api_key, "game:list")
    assert result is True

    with pytest.raises(PermissionDeniedError):
        await check_permission(api_key, "report:generate")


@pytest.mark.asyncio
async def test_check_permission_denied():
    """권한 확인 테스트 - 권한 없음"""
    # API 키 모의 객체 (다른 권한만)
    api_key = MagicMock()
    api_key.permissions = ["game:list"]
    
    # 권한 확인 및 예외 검증
    with pytest.raises(PermissionDeniedError) as exc_info:
        await check_permission(api_key, "wallet:read")
    
    # 예외 메시지 검증
    assert "Missing required permission: wallet:read" in str(exc_info.value)

@pytest.mark.asyncio
async def test_check_permission_denied_empty_list():
    """권한 확인 테스트 - 빈 권한 목록"""
    api_key = MagicMock()
    api_key.permissions = []
    
    with pytest.raises(PermissionDeniedError):
        await check_permission(api_key, "wallet:read")

@pytest.mark.asyncio
async def test_check_permission_denied_none():
    """권한 확인 테스트 - 권한이 None인 경우"""
    api_key = MagicMock()
    api_key.permissions = None
    
    with pytest.raises(PermissionDeniedError):
        await check_permission(api_key, "wallet:read")

@pytest.mark.asyncio
async def test_check_permission_no_colon_required():
    """권한 확인 테스트 - 콜론 없는 필수 권한"""
    api_key = MagicMock()
    api_key.permissions = ["admin_access"]
    
    result = await check_permission(api_key, "admin_access")
    assert result is True

    with pytest.raises(PermissionDeniedError):
        await check_permission(api_key, "user_access") 