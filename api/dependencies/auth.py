from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from typing import Dict, Any, List, Optional
import logging

from backend.db.database import get_db
from backend.services.auth.auth_service import AuthService
from backend.utils.request_context import get_request_attribute
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# API 키 헤더 정의
API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

async def get_current_partner_id(
    api_key: str = Depends(API_KEY_HEADER),
    db: Session = Depends(get_db)
) -> str:
    """
    현재 인증된 파트너의 ID 가져오기
    
    Returns:
        str: 파트너 ID
    
    Raises:
        HTTPException: 인증 실패 시
    """
    # 요청 컨텍스트에서 파트너 ID 확인
    partner_id = get_request_attribute("partner_id")
    if partner_id:
        return partner_id
    
    # 컨텍스트에 없는 경우 직접 인증
    auth_service = AuthService(db)
    api_key_info = await auth_service.validate_api_key(api_key)
    
    if not api_key_info:
        logger.warning(f"Invalid API key: {api_key[:5]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
    
    return api_key_info["partner_id"]

async def get_current_permissions(
    api_key: str = Depends(API_KEY_HEADER),
    db: Session = Depends(get_db)
) -> Dict[str, List[str]]:
    """
    현재 인증된 파트너의 권한 목록 가져오기
    
    Returns:
        Dict[str, List[str]]: 권한 목록
    
    Raises:
        HTTPException: 인증 실패 시
    """
    # 요청 컨텍스트에서 권한 확인
    permissions = get_request_attribute("permissions")
    if permissions:
        return permissions
    
    # 컨텍스트에 없는 경우 직접 인증
    auth_service = AuthService(db)
    api_key_info = await auth_service.validate_api_key(api_key)
    
    if not api_key_info:
        logger.warning(f"Invalid API key: {api_key[:5]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
    
    return api_key_info["permissions"]

async def verify_permissions(
    required_permission: str,
    permissions: Dict[str, List[str]] = Depends(get_current_permissions)
) -> None:
    """
    필요한 권한 확인
    
    Args:
        required_permission: 필요한 권한 문자열 (예: "wallet.read")
        permissions: 권한 목록
    
    Raises:
        HTTPException: 필요한 권한이 없음
    """
    # 권한 형식: "{resource}.{action}" 예: "wallet.read"
    resource, action = required_permission.split(".")
    
    # 권한 확인 로직
    allowed = False
    
    # 1. 정확한 리소스와 액션 일치 확인
    if resource in permissions and action in permissions[resource]:
        allowed = True
    
    # 2. 리소스에 대한 모든 권한 확인 ("*" 액션)
    elif resource in permissions and "*" in permissions[resource]:
        allowed = True
    
    # 3. 모든 리소스에 대한 특정 액션 권한 확인
    elif "*" in permissions and action in permissions["*"]:
        allowed = True
    
    # 4. 모든 리소스에 대한 모든 액션 권한 확인 (슈퍼 관리자)
    elif "*" in permissions and "*" in permissions["*"]:
        allowed = True
    
    if not allowed:
        logger.warning(f"Permission denied: {required_permission}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {required_permission}",
        )

async def get_ip_address(request: Request) -> str:
    """
    요청의 IP 주소 가져오기
    
    Args:
        request: FastAPI 요청 객체
        
    Returns:
        str: IP 주소
    """
    # 요청 컨텍스트에서 IP 주소 확인
    client_ip = get_request_attribute("client_ip")
    if client_ip:
        return client_ip
    
    # X-Forwarded-For 헤더를 확인 (프록시 뒤에 있는 경우)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # 첫 번째 IP만 사용 (쉼표로 구분된 목록일 수 있음)
        return forwarded_for.split(",")[0].strip()
    
    # 클라이언트 호스트 사용
    return request.client.host