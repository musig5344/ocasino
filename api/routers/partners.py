from fastapi import APIRouter, Depends, Query, Path, status, Body
from typing import Optional, List
import logging
from uuid import UUID

from backend.api.dependencies.auth import get_current_partner_id, verify_permissions
from backend.api.dependencies.db import get_db
from backend.api.dependencies.common import common_pagination_params, common_sort_params
from backend.models.schemas.partner import (
    PartnerCreate, PartnerUpdate, Partner, PartnerList,
    ApiKeyCreate, ApiKey, ApiKeyWithSecret, 
    PartnerSettingCreate, PartnerSetting
)
from backend.services.partner.partner_service import PartnerService
from backend.api.errors.exceptions import ResourceNotFoundException, ForbiddenException
from backend.utils.response_builder import success_response, paginated_response

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("", response_model=Partner, status_code=status.HTTP_201_CREATED)
async def create_partner(
    partner_data: PartnerCreate = Body(...),
    db = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    새 비즈니스 파트너 생성
    
    관리자 권한이 필요합니다.
    """
    # 관리자 권한 확인
    await verify_permissions("partners.create")
    
    partner_service = PartnerService(db)
    
    # 파트너 생성
    partner = await partner_service.create_partner(partner_data)
    
    logger.info(f"New partner created: {partner.id} ({partner.name}) by {current_partner_id}")
    
    return success_response(partner, status_code=status.HTTP_201_CREATED)

@router.get("", response_model=PartnerList)
async def list_partners(
    name: Optional[str] = Query(None, description="이름으로 필터링"),
    status: Optional[str] = Query(None, description="상태로 필터링 (active, inactive, suspended)"),
    partner_type: Optional[str] = Query(None, description="파트너 유형으로 필터링"),
    pagination: dict = Depends(common_pagination_params),
    sorting: dict = Depends(common_sort_params),
    db = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너 목록 조회
    
    관리자는 모든 파트너를 볼 수 있지만, 일반 파트너는 자신의 정보만 볼 수 있습니다.
    """
    partner_service = PartnerService(db)
    
    # 권한 확인
    is_admin = False
    try:
        # 관리자 권한 확인
        await verify_permissions("partners.read.all")
        is_admin = True
    except:
        # 일반 파트너는 자신의 정보만 조회 가능
        pass
    
    if not is_admin:
        # 자신의 정보만 조회
        partner = await partner_service.get_partner(current_partner_id)
        if not partner:
            return paginated_response([], 0, pagination["page"], pagination["page_size"])
        
        return paginated_response([partner], 1, pagination["page"], pagination["page_size"])
    
    # 관리자는 필터링된 목록 조회
    filters = {
        "name": name,
        "status": status,
        "partner_type": partner_type
    }
    
    # 필터 적용하여 파트너 목록 조회
    partners, total = await partner_service.list_partners(
        pagination["skip"], 
        pagination["limit"], 
        filters,
        sorting["sort_by"],
        sorting["sort_order"]
    )
    
    return paginated_response(
        partners, 
        total, 
        pagination["page"], 
        pagination["page_size"]
    )

@router.get("/{partner_id}", response_model=Partner)
async def get_partner(
    partner_id: UUID = Path(..., description="파트너 ID"),
    db = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너 세부 정보 조회
    
    파트너는 자신의 정보만 볼 수 있습니다.
    관리자는 모든 파트너 정보를 볼 수 있습니다.
    """
    # 자신의 정보 또는 관리자 권한 확인
    if str(partner_id) != current_partner_id:
        try:
            await verify_permissions("partners.read.all")
        except:
            raise ForbiddenException("You can only view your own partner information")
    
    partner_service = PartnerService(db)
    
    # 파트너 조회
    partner = await partner_service.get_partner(partner_id)
    if not partner:
        raise ResourceNotFoundException("Partner", str(partner_id))
    
    return success_response(partner)

@router.put("/{partner_id}", response_model=Partner)
async def update_partner(
    partner_data: PartnerUpdate = Body(...),
    partner_id: UUID = Path(..., description="파트너 ID"),
    db = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너 정보 업데이트
    
    파트너는 자신의 일부 정보만 업데이트할 수 있습니다.
    관리자는 모든 파트너 정보를 업데이트할 수 있습니다.
    """
    partner_service = PartnerService(db)
    
    # 권한에 따라 업데이트 가능한 필드 제한
    if str(partner_id) != current_partner_id:
        # 관리자 권한 확인
        try:
            await verify_permissions("partners.update.all")
        except:
            raise ForbiddenException("You can only update your own partner information")
    else:
        # 일반 파트너는 제한된 필드만 업데이트 가능
        restricted_fields = ["status", "commission_model", "commission_rate"]
        for field in restricted_fields:
            if getattr(partner_data, field, None) is not None:
                raise ForbiddenException(f"You cannot update the {field} field")
    
    # 파트너 업데이트
    updated_partner = await partner_service.update_partner(partner_id, partner_data)
    if not updated_partner:
        raise ResourceNotFoundException("Partner", str(partner_id))
    
    logger.info(f"Partner updated: {partner_id} by {current_partner_id}")
    
    return success_response(updated_partner)

@router.post("/{partner_id}/api-keys", response_model=ApiKeyWithSecret, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    api_key_data: ApiKeyCreate = Body(...),
    partner_id: UUID = Path(..., description="파트너 ID"),
    db = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너를 위한 새 API 키 생성
    
    파트너는 자신을 위한 API 키만 생성할 수 있습니다.
    관리자는 모든 파트너의 API 키를 생성할 수 있습니다.
    """
    # 자신을 위한 키 생성인지 확인
    if str(partner_id) != current_partner_id:
        # 관리자 권한 확인
        try:
            await verify_permissions("partners.api_keys.manage")
        except:
            raise ForbiddenException("You can only create API keys for yourself")
    
    partner_service = PartnerService(db)
    
    # API 키 생성
    api_key_result = await partner_service.create_api_key(partner_id, api_key_data)
    
    # 마스킹된 키 로깅 (보안을 위해)
    masked_key = f"{api_key_result['key'][:4]}...{api_key_result['key'][-4:]}"
    logger.info(f"API key created for partner {partner_id}: {masked_key}")
    
    return success_response(api_key_result, status_code=status.HTTP_201_CREATED)

@router.get("/{partner_id}/api-keys", response_model=List[ApiKey])
async def list_api_keys(
    partner_id: UUID = Path(..., description="파트너 ID"),
    db = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너의 API 키 목록 조회
    
    파트너는 자신의 API 키만 볼 수 있습니다.
    관리자는 모든 파트너의 API 키를 볼 수 있습니다.
    """
    # 자신의 키 목록 또는 관리자 권한 확인
    if str(partner_id) != current_partner_id:
        try:
            await verify_permissions("partners.api_keys.read")
        except:
            raise ForbiddenException("You can only view your own API keys")
    
    partner_service = PartnerService(db)
    
    # 파트너 확인
    partner = await partner_service.get_partner(partner_id)
    if not partner:
        raise ResourceNotFoundException("Partner", str(partner_id))
    
    # API 키 목록 조회
    api_keys = await partner_service.get_partner_api_keys(partner_id)
    
    return success_response(api_keys)

@router.delete("/{partner_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_api_key(
    key_id: UUID = Path(..., description="API 키 ID"),
    partner_id: UUID = Path(..., description="파트너 ID"),
    db = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    API 키 비활성화 (폐기)
    
    파트너는 자신의 API 키만 비활성화할 수 있습니다.
    관리자는 모든 파트너의 API 키를 비활성화할 수 있습니다.
    """
    partner_service = PartnerService(db)
    
    # API 키 소유자 확인
    key_owner = await partner_service.get_api_key_owner(key_id)
    if not key_owner:
        raise ResourceNotFoundException("API key", str(key_id))
    
    # 권한 확인
    if str(key_owner) != current_partner_id:
        # 관리자 권한 확인
        try:
            await verify_permissions("partners.api_keys.manage")
        except:
            raise ForbiddenException("You can only deactivate your own API keys")
    
    # API 키 비활성화
    success = await partner_service.deactivate_api_key(key_id)
    if not success:
        raise ResourceNotFoundException("API key", str(key_id))
    
    logger.info(f"API key {key_id} deactivated by {current_partner_id}")
    
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.post("/{partner_id}/settings", response_model=PartnerSetting)
async def create_or_update_setting(
    setting_data: PartnerSettingCreate = Body(...),
    partner_id: UUID = Path(..., description="파트너 ID"),
    db = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너 설정 생성 또는 업데이트
    
    파트너는 자신의 일부 설정만 변경할 수 있습니다.
    관리자는 모든 파트너의 모든 설정을 변경할 수 있습니다.
    """
    # 자신의 설정 또는 관리자 권한 확인
    if str(partner_id) != current_partner_id:
        try:
            await verify_permissions("partners.settings.manage")
        except:
            raise ForbiddenException("You can only update your own settings")
    else:
        # 일반 파트너는 제한된 설정만 변경 가능
        restricted_settings = ["commission", "limits", "risk"]
        if any(setting_data.key.startswith(prefix) for prefix in restricted_settings):
            raise ForbiddenException(f"You cannot modify this setting type: {setting_data.key}")
    
    partner_service = PartnerService(db)
    
    # 설정 업데이트
    setting = await partner_service.update_partner_setting(partner_id, setting_data)
    
    logger.info(f"Partner setting updated: {partner_id}/{setting_data.key} by {current_partner_id}")
    
    return success_response(setting)

@router.get("/{partner_id}/settings", response_model=List[PartnerSetting])
async def list_settings(
    partner_id: UUID = Path(..., description="파트너 ID"),
    db = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너 설정 목록 조회
    
    파트너는 자신의 설정만 볼 수 있습니다.
    관리자는 모든 파트너의 설정을 볼 수 있습니다.
    """
    # 자신의 설정 또는 관리자 권한 확인
    if str(partner_id) != current_partner_id:
        try:
            await verify_permissions("partners.settings.read")
        except:
            raise ForbiddenException("You can only view your own settings")
    
    partner_service = PartnerService(db)
    
    # 파트너 확인
    partner = await partner_service.get_partner(partner_id)
    if not partner:
        raise ResourceNotFoundException("Partner", str(partner_id))
    
    # 설정 목록 조회
    settings = await partner_service.get_partner_settings(partner_id)
    
    return success_response(settings)