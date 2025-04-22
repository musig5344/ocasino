from fastapi import APIRouter, Depends, Body, Query, Path, status
from sqlalchemy.orm import Session
from typing import Optional
import logging
import secrets

from backend.api.dependencies.db import get_db
from backend.api.dependencies.auth import get_current_partner_id, verify_permissions
from backend.models.schemas.auth import (
    ApiKeyCreate, ApiKeyResponse, ApiKeyList, 
    IpWhitelistCreate, IpWhitelistResponse, IpWhitelistList
)
from backend.services.auth.api_key_service import AuthenticationService
from backend.api.errors.exceptions import ResourceNotFoundException, ForbiddenException

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/keys", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    api_key_data: ApiKeyCreate,
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db)
):
    """
    새 API 키 생성
    
    권한이 있는 파트너만 API 키를 생성할 수 있습니다.
    """
    auth_service = AuthenticationService(db)
    
    # 키 생성 요청자가 대상 파트너와 동일하거나 관리자인지 확인
    if partner_id != api_key_data.partner_id:
        # 관리자 권한 확인
        await verify_permissions("api_keys.manage")
    
    # API 키 생성
    api_key = await auth_service.generate_api_key(
        partner_id=api_key_data.partner_id,
        permissions=api_key_data.permissions,
        expires_in_days=api_key_data.expires_in_days
    )
    
    if not api_key:
        raise ResourceNotFoundException("Partner", api_key_data.partner_id)
    
    # 생성된 API 키 로깅 (보안을 위해 일부만 로깅)
    masked_key = f"{api_key.key[:4]}...{api_key.key[-4:]}"
    logger.info(f"API key created for partner {api_key_data.partner_id}: {masked_key}")
    
    return ApiKeyResponse(
        api_key_id=api_key.id,
        key=api_key.key,  # 생성 시 한 번만 전체 키 반환
        partner_id=api_key_data.partner_id,
        status=api_key.status,
        permissions=api_key_data.permissions,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at
    )

@router.get("/keys", response_model=ApiKeyList)
async def list_api_keys(
    partner_id: Optional[str] = Query(None, description="파트너 ID로 필터링"),
    status: Optional[str] = Query(None, description="상태로 필터링 (active, revoked)"),
    current_partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db)
):
    """
    API 키 목록 조회
    
    파트너는 자신의 API 키만 볼 수 있습니다.
    관리자는 모든 API 키를 볼 수 있습니다.
    """
    auth_service = AuthenticationService(db)
    
    # 다른 파트너의 키를 조회하려면 관리자 권한 필요
    if partner_id and partner_id != current_partner_id:
        # 관리자 권한 확인
        try:
            await verify_permissions("api_keys.read")
        except:
            # 권한이 없으면 자신의 키만 조회
            partner_id = current_partner_id
    else:
        # 파트너 ID를 지정하지 않았으면 자신의 키만 조회
        partner_id = current_partner_id
    
    # API 키 목록 조회
    keys = await auth_service.list_api_keys(partner_id=partner_id, status=status)
    
    # 응답에서 전체 키 값은 제거 (보안상 이유로)
    api_keys = []
    for key in keys:
        masked_key = f"{key.key[:4]}...{key.key[-4:]}" if key.key else None
        api_keys.append({
            "api_key_id": key.id,
            "key": masked_key,
            "partner_id": key.partner_id,
            "status": key.status,
            "created_at": key.created_at,
            "expires_at": key.expires_at,
            "last_used_at": key.last_used_at
        })
    
    return ApiKeyList(
        items=api_keys,
        count=len(api_keys)
    )

@router.delete("/keys/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    api_key_id: str = Path(..., description="API 키 ID"),
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db)
):
    """
    API 키 취소
    
    파트너는 자신의 API 키만 취소할 수 있습니다.
    관리자는 모든 API 키를 취소할 수 있습니다.
    """
    auth_service = AuthenticationService(db)
    
    # API 키 소유자 확인
    key_owner = await auth_service.get_api_key_owner(api_key_id)
    if not key_owner:
        raise ResourceNotFoundException("API Key", api_key_id)
    
    # 권한 확인
    if key_owner != partner_id:
        # 관리자 권한 확인
        try:
            await verify_permissions("api_keys.manage")
        except:
            raise ForbiddenException("You can only revoke your own API keys")
    
    # API 키 취소
    success = await auth_service.revoke_api_key(api_key_id)
    if not success:
        raise ResourceNotFoundException("API Key", api_key_id)
    
    logger.info(f"API key {api_key_id} revoked by partner {partner_id}")

@router.post("/ip-whitelist", response_model=IpWhitelistResponse, status_code=status.HTTP_201_CREATED)
async def add_ip_to_whitelist(
    whitelist_data: IpWhitelistCreate,
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db)
):
    """
    IP 주소를 화이트리스트에 추가
    
    파트너는 자신의 API 키에 대해서만 IP를 추가할 수 있습니다.
    관리자는 모든 API 키에 IP를 추가할 수 있습니다.
    """
    auth_service = AuthenticationService(db)
    
    # API 키 소유자 확인
    key_owner = await auth_service.get_api_key_owner(whitelist_data.api_key_id)
    if not key_owner:
        raise ResourceNotFoundException("API Key", whitelist_data.api_key_id)
    
    # 권한 확인
    if key_owner != partner_id:
        # 관리자 권한 확인
        try:
            await verify_permissions("api_keys.manage")
        except:
            raise ForbiddenException("You can only manage your own API keys")
    
    # IP 주소 추가
    whitelist_entry = await auth_service.add_ip_to_whitelist(
        api_key_id=whitelist_data.api_key_id,
        ip_address=whitelist_data.ip_address,
        description=whitelist_data.description
    )
    
    logger.info(f"IP {whitelist_data.ip_address} added to whitelist for API key {whitelist_data.api_key_id}")
    
    return IpWhitelistResponse(
        id=whitelist_entry.id,
        api_key_id=whitelist_entry.api_key_id,
        ip_address=whitelist_entry.ip_address,
        description=whitelist_entry.description,
        created_at=whitelist_entry.created_at
    )

@router.get("/ip-whitelist", response_model=IpWhitelistList)
async def list_ip_whitelist(
    api_key_id: Optional[str] = Query(None, description="API 키 ID로 필터링"),
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db)
):
    """
    IP 화이트리스트 조회
    
    파트너는 자신의 API 키에 대한 화이트리스트만 볼 수 있습니다.
    관리자는 모든 화이트리스트를 볼 수 있습니다.
    """
    auth_service = AuthenticationService(db)
    
    # API 키 소유자 확인 (특정 API 키 ID가 지정된 경우)
    if api_key_id:
        key_owner = await auth_service.get_api_key_owner(api_key_id)
        if not key_owner:
            raise ResourceNotFoundException("API Key", api_key_id)
        
        # 권한 확인
        if key_owner != partner_id:
            # 관리자 권한 확인
            try:
                await verify_permissions("api_keys.read")
            except:
                raise ForbiddenException("You can only view your own IP whitelist")
    
    # IP 화이트리스트 조회
    whitelist_entries = await auth_service.list_ip_whitelist(
        partner_id=partner_id,
        api_key_id=api_key_id,
        is_admin=(api_key_id is not None and key_owner != partner_id)
    )
    
    return IpWhitelistList(
        items=whitelist_entries,
        count=len(whitelist_entries)
    )

@router.delete("/ip-whitelist/{whitelist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_ip_from_whitelist(
    whitelist_id: str = Path(..., description="화이트리스트 항목 ID"),
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db)
):
    """
    IP 주소를 화이트리스트에서 제거
    
    파트너는 자신의 API 키에 대한 화이트리스트 항목만 제거할 수 있습니다.
    관리자는 모든 화이트리스트 항목을 제거할 수 있습니다.
    """
    auth_service = AuthenticationService(db)
    
    # 화이트리스트 항목의 소유자 확인
    whitelist_owner = await auth_service.get_whitelist_owner(whitelist_id)
    if not whitelist_owner:
        raise ResourceNotFoundException("IP Whitelist Entry", whitelist_id)
    
    # 권한 확인
    if whitelist_owner != partner_id:
        # 관리자 권한 확인
        try:
            await verify_permissions("api_keys.manage")
        except:
            raise ForbiddenException("You can only remove your own IP whitelist entries")
    
    # 화이트리스트 항목 제거
    ip_address = await auth_service.remove_ip_from_whitelist(whitelist_id)
    if not ip_address:
        raise ResourceNotFoundException("IP Whitelist Entry", whitelist_id)
    
    logger.info(f"IP {ip_address} removed from whitelist by partner {partner_id}")
    
@router.get("/verify", status_code=status.HTTP_200_OK)
async def verify_api_key(
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db)
):
    """
    API 키 검증 엔드포인트
    
    API 키가 유효한지 빠르게 확인하는 데 사용할 수 있습니다.
    """
    return {
        "valid": True,
        "partner_id": partner_id
    }