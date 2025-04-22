from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from typing import Optional, Dict, Any
import logging

from backend.core.config import settings
from backend.db.database import get_db
from backend.services.auth.api_key_service import AuthenticationService
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# API 키 헤더 정의
API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

async def get_api_key_from_header(
    api_key: str = Depends(API_KEY_HEADER),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    헤더에서 API 키를 가져와 검증
    
    Returns:
        Dict: API 키 정보 (파트너 ID, 권한 등)
    
    Raises:
        HTTPException: 유효하지 않은 API 키
    """
    auth_service = AuthenticationService(db)
    api_key_info = await auth_service.validate_api_key(api_key)
    
    if not api_key_info:
        logger.warning(f"Invalid API key: {api_key[:5]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
    
    # 마지막 사용 시간 업데이트
    await auth_service.update_api_key_last_used(api_key)
    
    return api_key_info

async def get_current_partner_id(
    api_key_info: Dict[str, Any] = Depends(get_api_key_from_header)
) -> str:
    """
    현재 인증된 파트너의 ID 가져오기
    
    Returns:
        str: 파트너 ID
    """
    return api_key_info["partner_id"]

async def get_ip_address(request: Request) -> str:
    """
    요청의 IP 주소 가져오기
    
    Args:
        request: FastAPI 요청 객체
        
    Returns:
        str: IP 주소
    """
    # X-Forwarded-For 헤더를 확인 (프록시 뒤에 있는 경우)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # 첫 번째 IP만 사용 (쉼표로 구분된 목록일 수 있음)
        return forwarded_for.split(",")[0].strip()
    
    # 클라이언트 호스트 사용
    return request.client.host

async def verify_ip_whitelist(
    request: Request,
    api_key_info: Dict[str, Any] = Depends(get_api_key_from_header),
    db: Session = Depends(get_db)
) -> None:
    """
    IP 화이트리스트 검증
    
    Args:
        request: FastAPI 요청 객체
        api_key_info: API 키 정보
        db: 데이터베이스 세션
    
    Raises:
        HTTPException: IP 주소가 화이트리스트에 없음
    """
    # IP 화이트리스팅이 비활성화된 경우 검증 건너뛰기
    if not settings.ENABLE_IP_WHITELIST:
        return
    
    # 현재 IP 가져오기
    ip_address = await get_ip_address(request)
    
    # 화이트리스트 확인
    auth_service = AuthenticationService(db)
    is_whitelisted = await auth_service.check_ip_whitelist(
        api_key_info["partner_key_id"],
        ip_address
    )
    
    if not is_whitelisted:
        logger.warning(f"IP not whitelisted: {ip_address} for partner {api_key_info['partner_id']}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"IP address {ip_address} is not whitelisted",
        )

async def verify_permissions(
    required_permission: str,
    api_key_info: Dict[str, Any] = Depends(get_api_key_from_header)
) -> None:
    """
    필요한 권한 확인
    
    Args:
        required_permission: 필요한 권한 문자열 (예: "wallet.read")
        api_key_info: API 키 정보
    
    Raises:
        HTTPException: 필요한 권한이 없음
    """
    permissions = api_key_info.get("permissions", {})
    
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
        logger.warning(f"Permission denied: {required_permission} for partner {api_key_info['partner_id']}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {required_permission}",
        )