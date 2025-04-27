from fastapi import APIRouter, Depends, Query, Path, status, Body, HTTPException, Response
from typing import Optional, List, Dict, Any, Annotated
import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

# --- Add missing imports ---
from backend.core.schemas import StandardResponse, PaginatedResponse, PaginatedData
from backend.utils.response import success_response, paginated_response

# --- Updated Imports --- 
# from backend.api.dependencies.auth import get_current_partner_id, get_current_permissions # 이전 경로 주석 처리
# from backend.api.dependencies.db import get_db # 이전 경로 주석 처리
# from backend.api.dependencies.common import common_pagination_params, common_sort_params # 이전 경로 주석 처리
from backend.core.dependencies import (
    get_db, 
    get_current_partner_id, 
    get_current_permissions,
    common_pagination_params,
    common_sort_params
) # 새로운 공통 의존성 사용

# Import from the new partners module
from backend.partners.schemas import (
    PartnerCreate, PartnerUpdate, Partner, PartnerList,
    ApiKeyCreate, ApiKey, ApiKeyWithSecret, 
    PartnerSettingCreate, PartnerSetting, PartnerSettingList,
    PartnerIP, PartnerIPCreate, PartnerIPList
)
from backend.partners.dependencies import get_partner_service # Import from new location
from backend.partners.service import PartnerService # Corrected path

# Import exceptions and common elements
from backend.core.exceptions import PartnerNotFoundError, PermissionDeniedError, AuthorizationError, ConflictError, ValidationError
# Use common ErrorResponse from core schemas
from backend.core.schemas import ErrorResponse # 경로 수정

# TODO: Define dependency for PartnerService specific to this module/router
# Temporarily keep old dependency, needs review
# from backend.api.dependencies.common import get_partner_service # Remove old import

router = APIRouter() # Prefix will be added when including the router in api.py
logger = logging.getLogger(__name__)

# --- Partner CRUD Endpoints --- 

@router.post(
    "", 
    # Use standard response wrapper
    response_model=StandardResponse[Partner], 
    status_code=status.HTTP_201_CREATED, 
    summary="신규 파트너 생성 (관리자 전용)", 
    description="""
    새로운 비즈니스 파트너(운영사, 어그리게이터 등)를 시스템에 등록합니다. 
    
    이 작업은 `partners.create` 권한을 가진 관리자만 수행할 수 있습니다.
    파트너 코드(code)는 시스템 전체에서 고유해야 합니다.
    """, 
    responses={
        status.HTTP_201_CREATED: {"description": "파트너가 성공적으로 생성되었습니다."},
        # Other error responses are now handled globally
    }
)
async def create_partner(
    # Non-default args first
    partner_data: PartnerCreate, 
    # Depends args last
    service: PartnerService = Depends(get_partner_service), 
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    새로운 비즈니스 파트너를 생성합니다.
    
    - **partner_data**: 생성할 파트너의 상세 정보 (PartnerCreate 스키마).
    
    **권한 요구사항:** `partners.create`
    """
    if "partners.create" not in requesting_permissions:
         # Raise specific permission error
         raise PermissionDeniedError("Permission denied to create partners")
         
    # No need for try/except for handled exceptions (NotFoundError, ConflictError etc.)
    # Global handlers will catch them.
    # Only catch truly unexpected errors if specific handling is needed here.
    partner = await service.create(partner_data) # Use BaseService create
    logger.info(f"New partner created: {partner.id} ({partner.code}) by {requesting_partner_id}")
    # Return standard success response
    return success_response(data=partner, message="Partner created successfully.")

@router.get(
    "", 
    # Use standard paginated response wrapper
    response_model=PaginatedResponse[Partner], 
    summary="파트너 목록 조회", 
    description="""
    파트너 목록을 조회합니다. 페이지네이션, 필터링(이름, 상태, 유형), 정렬 기능을 지원합니다.
    
    - **관리자 (`partners.read.all` 권한):** 모든 파트너 목록을 필터링하여 조회할 수 있습니다.
    - **일반 파트너 (`partners.read.self` 권한):** 자신의 파트너 정보만 조회됩니다 (필터링/정렬 적용 안 됨).
    """, 
    responses={
        status.HTTP_200_OK: {"description": "파트너 목록 조회 성공"},
        # Other error responses handled globally
    }
)
async def list_partners(
    # Non-default/Query args first
    name: Optional[str] = Query(None, description="파트너 이름 부분 검색", example="Casino"),
    status: Optional[str] = Query(None, description="파트너 상태 필터", example="active"),
    partner_type: Optional[str] = Query(None, description="파트너 유형 필터", example="operator"),
    # Depends args last
    pagination: Dict[str, Any] = Depends(common_pagination_params),
    sorting: Dict[str, Optional[str]] = Depends(common_sort_params),
    service: PartnerService = Depends(get_partner_service), 
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    파트너 목록을 필터링하고 정렬하여 조회합니다.
    
    - **name**: 파트너 이름 부분 문자열 필터 (대소문자 무시).
    - **status**: 파트너 상태 필터.
    - **partner_type**: 파트너 유형 필터.
    - **pagination**: 페이지네이션 파라미터 (`offset`, `limit`, `page`).
    - **sorting**: 정렬 파라미터 (`sort_by`, `sort_order`).
    
    **권한 요구사항:** `partners.read.self` 또는 `partners.read.all`
    """
    can_read_all = "partners.read.all" in requesting_permissions
    can_read_self = "partners.read.self" in requesting_permissions

    if not can_read_all and not can_read_self:
         raise PermissionDeniedError("Permission denied to list partners")

    # Non-admins can only view themselves
    if not can_read_all:
        # Use service.get which raises NotFoundError handled globally
        partner = await service.get(requesting_partner_id) 
        # Simulate pagination for a single item
        return paginated_response(items=[partner], total=1, page=1, page_size=1)
            
    # Admins can list all with filters
    filters = {"name__icontains": name, "status": status, "partner_type": partner_type}
    # Remove None values from filters
    active_filters = {k: v for k, v in filters.items() if v is not None}
    
    # Use BaseService list method
    partners, total = await service.list(
        skip=pagination["offset"],
        limit=pagination["limit"], 
        filters=active_filters,
        sort_by=sorting.get("sort_by"),
        sort_order=sorting.get("sort_order", "asc")
    )
    # Use paginated response utility
    return paginated_response(
        items=partners, 
        total=total, 
        page=pagination.get("page", 1), # Get page from pagination dict
        page_size=pagination["limit"]
    )

@router.get(
    "/{partner_id}", 
    # Use standard response wrapper
    response_model=StandardResponse[Partner], 
    summary="특정 파트너 상세 정보 조회", 
    description="""
    지정된 ID의 파트너 상세 정보를 조회합니다.
    
    - **파트너 (`partners.read.self` 권한):** 자신의 파트너 정보만 조회 가능합니다.
    - **관리자 (`partners.read.all` 권한):** ID로 지정된 모든 파트너의 정보를 조회 가능합니다.
    """, 
    responses={
        status.HTTP_200_OK: {"description": "파트너 정보 조회 성공"},
        # Other error responses handled globally (401, 403, 404, 500)
    }
)
async def read_partner(
    # Non-default path arg first
    partner_id: UUID = Path(..., description="조회할 파트너의 고유 ID"),
    # Depends args last
    service: PartnerService = Depends(get_partner_service), 
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    특정 파트너의 상세 정보를 조회합니다.
    
    - **partner_id**: 조회 대상 파트너의 UUID.
    
    **권한 요구사항:** `partners.read.self` (자신의 정보) 또는 `partners.read.all` (타 파트너 정보 포함)
    """
    can_read_all = "partners.read.all" in requesting_permissions
    can_read_self = "partners.read.self" in requesting_permissions

    if partner_id != requesting_partner_id: 
        if not can_read_all:
             raise PermissionDeniedError("Permission denied to view this partner's details")
    elif not can_read_self:
        # Deny if they can't read self, even if ID matches (edge case)
        raise PermissionDeniedError("Permission denied to view your own details")
         
    # Use service.get, global handler catches NotFoundError
    partner = await service.get(partner_id)
    return success_response(data=partner)

@router.put(
    "/{partner_id}", 
    # Use standard response wrapper
    response_model=StandardResponse[Partner], 
    summary="파트너 정보 업데이트", 
    description="""
    지정된 ID의 파트너 정보를 업데이트합니다. 요청 본문에 포함된 필드만 업데이트됩니다.
    
    - **파트너 (`partners.update.self` 권한):** 자신의 파트너 정보만 업데이트 가능합니다.
    - **관리자 (`partners.update.all` 권한):** 모든 파트너의 정보를 업데이트 가능합니다.
    """, 
    responses={
        status.HTTP_200_OK: {"description": "파트너 정보 업데이트 성공"},
        # Other error responses handled globally (401, 403, 404, 409, 422, 500)
    }
)
async def update_partner(
    partner_id: Annotated[UUID, Path(..., description="업데이트할 파트너의 고유 ID")],
    service: Annotated[PartnerService, Depends(get_partner_service)], 
    requesting_partner_id: Annotated[UUID, Depends(get_current_partner_id)],
    requesting_permissions: Annotated[List[str], Depends(get_current_permissions)],
    partner_update: Annotated[PartnerUpdate, Body()] 
):
    """
    파트너 정보를 업데이트합니다.
    
    - **partner_id**: 업데이트 대상 파트너의 UUID.
    - **partner_update**: 업데이트할 파트너 정보 (PartnerUpdate 스키마).
    
    **권한 요구사항:** `partners.update.self` 또는 `partners.update.all`
    """
    can_update_all = "partners.update.all" in requesting_permissions
    can_update_self = "partners.update.self" in requesting_permissions

    if partner_id != requesting_partner_id:
        if not can_update_all:
             raise PermissionDeniedError("Permission denied to update this partner")
    elif not can_update_self:
         raise PermissionDeniedError("Permission denied to update your own details")

    # Use service.update, global handler catches NotFoundError, ConflictError, ValidationError
    updated_partner = await service.update(partner_id, partner_update)
    logger.info(f"Partner {partner_id} updated by {requesting_partner_id}")
    return success_response(data=updated_partner, message="Partner updated successfully.")

# TODO: Implement DELETE endpoint (soft delete recommended)
# @router.delete("/{partner_id}", status_code=status.HTTP_204_NO_CONTENT, ...)

# --- API Key Management Endpoints ---

@router.post(
    "/{partner_id}/api-keys", 
    # Return specific schema for secret key
    response_model=StandardResponse[ApiKeyWithSecret], 
    status_code=status.HTTP_201_CREATED,
    tags=["Partner API Keys"],
    summary="파트너를 위한 새 API 키 생성",
    description="생성된 비밀 키는 이 응답에서만 반환되므로 안전하게 저장해야 합니다.",
    responses={
        status.HTTP_201_CREATED: {"description": "API 키 생성 성공"},
        # Other error responses handled globally
    }
)
async def create_api_key(
    partner_id: Annotated[UUID, Path(..., description="API 키를 생성할 파트너 ID")],
    service: Annotated[PartnerService, Depends(get_partner_service)], 
    requesting_partner_id: Annotated[UUID, Depends(get_current_partner_id)],
    requesting_permissions: Annotated[List[str], Depends(get_current_permissions)],
    api_key_data: Annotated[ApiKeyCreate, Body()]
):
    """
    파트너를 위한 새 API 키를 생성합니다.
    
    **권한 요구사항:** `api_keys.manage.self` 또는 `api_keys.manage.all`
    """
    # Check permissions: Can the requesting partner manage keys for the target partner_id?
    can_manage_all = "partners.apikeys.manage.all" in requesting_permissions
    can_manage_self = "partners.apikeys.manage.self" in requesting_permissions
    
    is_managing_self = (partner_id == requesting_partner_id)

    if not ((is_managing_self and can_manage_self) or can_manage_all):
        raise PermissionDeniedError("Permission denied to create API keys for this partner")

    # Service method handles NotFoundError if partner_id is invalid
    created_key, secret = await service.create_api_key(partner_id, api_key_data)
    
    # Combine the created key (DB model) and the secret into the response schema
    response_data = ApiKeyWithSecret(
        **created_key.__dict__, # Convert model to dict for schema validation
        secret=secret
    )
    logger.info(f"API Key {created_key.id} created for partner {partner_id} by {requesting_partner_id}")
    # Return standard response with the combined data
    return success_response(data=response_data, message="API Key created successfully. Store the secret securely.")

@router.get(
    "/{partner_id}/api-keys", 
    # Paginated response for list of ApiKey (without secret)
    response_model=PaginatedResponse[ApiKey], 
    tags=["Partner API Keys"],
    summary="파트너의 API 키 목록 조회",
    description="활성 API 키 목록만 반환합니다 (비밀 키 제외).",
    responses={
        status.HTTP_200_OK: {"description": "API 키 목록 조회 성공"},
        # Other error responses handled globally
    }
)
async def list_api_keys(
    # Non-default path arg first
    partner_id: UUID = Path(..., description="API 키 목록을 조회할 파트너 ID"),
    # Depends args last
    pagination: Dict[str, Any] = Depends(common_pagination_params),
    service: PartnerService = Depends(get_partner_service), 
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    파트너의 활성 API 키 목록을 조회합니다.
    
    **권한 요구사항:** `api_keys.read.self` 또는 `api_keys.read.all`
    """
    can_manage_all = "partners.apikeys.manage.all" in requesting_permissions # Or separate read perm?
    can_manage_self = "partners.apikeys.manage.self" in requesting_permissions
    is_viewing_self = (partner_id == requesting_partner_id)

    if not ((is_viewing_self and can_manage_self) or can_manage_all):
        raise PermissionDeniedError("Permission denied to list API keys for this partner")

    # Assuming service.list_api_keys returns List[ApiKeyModel]
    # Need to adapt this if pagination is implemented in the service/repo layer
    api_keys = await service.list_api_keys(partner_id)
    
    # Manual pagination for now (replace with service/repo pagination later)
    total = len(api_keys)
    start = pagination["offset"]
    end = start + pagination["limit"]
    paginated_keys = api_keys[start:end]
    
    # Use paginated response utility
    return paginated_response(
        items=paginated_keys, 
        total=total,
        page=pagination.get("page", 1),
        page_size=pagination["limit"]
    )

@router.delete(
    "/{partner_id}/api-keys/{key_id}", 
    # Use standard response for success message, no data needed on 204
    response_model=StandardResponse[None], 
    status_code=status.HTTP_200_OK, # Return 200 OK with message
    tags=["Partner API Keys"],
    summary="파트너 API 키 비활성화",
    description="API 키를 비활성화합니다 (삭제가 아닌 상태 변경).",
    responses={
        status.HTTP_200_OK: {"description": "API 키 비활성화 성공"},
        # Other error responses handled globally (401, 403, 404)
    }
)
async def deactivate_api_key(
    # Non-default path args first
    partner_id: UUID = Path(..., description="API 키가 속한 파트너 ID"),
    key_id: UUID = Path(..., description="비활성화할 API 키 ID"),
    # Depends args last
    service: PartnerService = Depends(get_partner_service), 
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    파트너의 API 키를 비활성화합니다.
    
    **권한 요구사항:** `api_keys.manage.self` 또는 `api_keys.manage.all`
    """
    can_manage_all = "partners.apikeys.manage.all" in requesting_permissions 
    can_manage_self = "partners.apikeys.manage.self" in requesting_permissions
    is_managing_self = (partner_id == requesting_partner_id)

    if not ((is_managing_self and can_manage_self) or can_manage_all):
        raise PermissionDeniedError("Permission denied to deactivate API keys for this partner")
        
    # Service handles ResourceNotFoundError if key or partner not found
    success = await service.deactivate_api_key(partner_id, key_id)
    # The service method now might raise if it fails, handled globally.
    # If it returns False, maybe raise a BusinessLogicError?
    # if not success:
    #     raise BusinessLogicError("Failed to deactivate API key, it might be already inactive or another issue occurred.")
        
    logger.info(f"API Key {key_id} for partner {partner_id} deactivated by {requesting_partner_id}")
    # Return standard success response instead of 204
    return success_response(message="API key deactivated successfully.") 
    # If 204 No Content is strongly preferred:
    # return Response(status_code=status.HTTP_204_NO_CONTENT)

# --- Partner Settings Endpoints --- 

@router.put(
    "/{partner_id}/settings/{setting_key}", 
    # Use standard response wrapper
    response_model=StandardResponse[PartnerSetting], 
    tags=["Partner Settings"],
    summary="파트너 설정 생성 또는 업데이트",
    description="지정한 키의 파트너 설정을 생성하거나 업데이트합니다.",
    responses={
        status.HTTP_200_OK: {"description": "설정 업데이트 성공"}, 
        status.HTTP_201_CREATED: {"description": "새 설정 생성 성공"},
        # Other error responses handled globally
    }
    # status_code will be determined by whether it was created or updated
)
async def update_or_create_partner_setting(
    partner_id: Annotated[UUID, Path(..., description="설정을 관리할 파트너 ID")],
    setting_key: Annotated[str, Path(..., description="관리할 설정의 키")],
    service: Annotated[PartnerService, Depends(get_partner_service)], 
    requesting_partner_id: Annotated[UUID, Depends(get_current_partner_id)],
    requesting_permissions: Annotated[List[str], Depends(get_current_permissions)],
    setting_data: Annotated[PartnerSettingCreate, Body()]
):
    """
    파트너 설정을 생성하거나 업데이트합니다.
    
    **권한 요구사항:** `settings.manage.self` 또는 `settings.manage.all`
    """
    # Permission check
    can_manage_all = "partners.settings.manage.all" in requesting_permissions 
    can_manage_self = "partners.settings.manage.self" in requesting_permissions
    is_managing_self = (partner_id == requesting_partner_id)
    
    if not ((is_managing_self and can_manage_self) or can_manage_all):
         raise PermissionDeniedError("Permission denied to manage settings for this partner")
         
    # Ensure setting_key from path matches data if necessary, 
    # or pass setting_key to service explicitly.
    # Here, we assume the service uses setting_data.setting_key implicitly.
    if setting_key != setting_data.setting_key:
         raise ValidationError(f"Setting key in path ({setting_key}) does not match key in body ({setting_data.setting_key}).")

    # Service method handles PartnerNotFoundError
    result_setting, created = await service.update_or_create_partner_setting(partner_id, setting_data)
    
    status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    message = "Setting created successfully." if created else "Setting updated successfully."
    logger.info(f"Setting '{setting_key}' for partner {partner_id} {'created' if created else 'updated'} by {requesting_partner_id}")

    # Return standard response with appropriate status code
    # Need to return JSONResponse directly to set status code dynamically
    response_content = success_response(data=result_setting, message=message).model_dump()
    return JSONResponse(content=response_content, status_code=status_code)

@router.get(
    "/{partner_id}/settings", 
    # Standard paginated response for PartnerSetting list
    response_model=PaginatedResponse[PartnerSetting], 
    tags=["Partner Settings"],
    summary="특정 파트너의 설정 목록 조회",
    description="파트너의 설정 목록을 조회합니다.",
    responses={
        status.HTTP_200_OK: {"description": "설정 목록 조회 성공"},
        # Error responses handled globally
    }
)
async def list_partner_settings(
    # Non-default path arg first
    partner_id: UUID = Path(..., description="설정 목록을 조회할 파트너 ID"),
    # Depends args last
    pagination: Dict[str, Any] = Depends(common_pagination_params), # Add pagination
    service: PartnerService = Depends(get_partner_service), 
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    파트너의 설정 목록을 조회합니다.
    
    **권한 요구사항:** `settings.read.self` 또는 `settings.read.all`
    """
    can_read_all = "partners.settings.read.all" in requesting_permissions 
    can_read_self = "partners.settings.read.self" in requesting_permissions
    is_viewing_self = (partner_id == requesting_partner_id)

    if not ((is_viewing_self and can_read_self) or can_read_all):
         raise PermissionDeniedError("Permission denied to list settings for this partner")
         
    # Assuming service.list_partner_settings returns List[PartnerSettingModel]
    # Need to adapt this for pagination
    settings_list = await service.list_partner_settings(partner_id)
    
    # Manual pagination (replace with service/repo layer pagination later)
    total = len(settings_list)
    start = pagination["offset"]
    end = start + pagination["limit"]
    paginated_settings = settings_list[start:end]
    
    return paginated_response(
        items=paginated_settings, 
        total=total,
        page=pagination.get("page", 1),
        page_size=pagination["limit"]
    )

# --- Partner IP Whitelist Endpoints --- 

@router.get(
    "/{partner_id}/whitelist", 
    # Standard paginated response for PartnerIP list
    response_model=PaginatedResponse[PartnerIP], 
    tags=["Partner IP Whitelist"],
    summary="파트너 IP 화이트리스트 조회",
    description="파트너의 활성 IP 화이트리스트를 조회합니다.",
    responses={
        status.HTTP_200_OK: {"description": "IP 화이트리스트 조회 성공"},
        # Error responses handled globally
    }
)
async def list_partner_ips(
    # Non-default path arg first
    partner_id: UUID = Path(..., description="IP 화이트리스트를 조회할 파트너 ID"),
    # Depends args last
    pagination: Dict[str, Any] = Depends(common_pagination_params), # Add pagination
    service: PartnerService = Depends(get_partner_service), 
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    파트너의 활성 IP 화이트리스트를 조회합니다.
    
    **권한 요구사항:** `whitelist.read.self` 또는 `whitelist.read.all`
    """
    can_read_all = "partners.whitelist.read.all" in requesting_permissions 
    can_read_self = "partners.whitelist.read.self" in requesting_permissions
    is_viewing_self = (partner_id == requesting_partner_id)

    if not ((is_viewing_self and can_read_self) or can_read_all):
         raise PermissionDeniedError("Permission denied to list IPs for this partner")
         
    # Assuming service.list_partner_ips returns List[PartnerIPModel]
    # Need pagination support in service/repo
    ip_list = await service.list_partner_ips(partner_id)
    
    # Manual pagination
    total = len(ip_list)
    start = pagination["offset"]
    end = start + pagination["limit"]
    paginated_ips = ip_list[start:end]
    
    return paginated_response(
        items=paginated_ips,
        total=total,
        page=pagination.get("page", 1),
        page_size=pagination["limit"]
    )

@router.post(
    "/{partner_id}/whitelist", 
    # Standard response wrapper
    response_model=StandardResponse[PartnerIP], 
    status_code=status.HTTP_201_CREATED, 
    tags=["Partner IP Whitelist"],
    summary="파트너 IP 화이트리스트 추가",
    description="새 IP 주소(IPv4/IPv6) 또는 CIDR 블록을 추가합니다.",
    responses={
        status.HTTP_201_CREATED: {"description": "IP 추가 성공"},
        # Error responses handled globally (401, 403, 404, 409)
    }
)
async def add_partner_ip(
    partner_id: Annotated[UUID, Path(..., description="IP를 추가할 파트너 ID")],
    service: Annotated[PartnerService, Depends(get_partner_service)], 
    requesting_partner_id: Annotated[UUID, Depends(get_current_partner_id)],
    requesting_permissions: Annotated[List[str], Depends(get_current_permissions)],
    ip_data: Annotated[PartnerIPCreate, Body()]
):
    """
    파트너의 IP 화이트리스트에 새 IP 주소를 추가합니다.
    
    **권한 요구사항:** `whitelist.manage.self` 또는 `whitelist.manage.all`
    """
    can_manage_all = "partners.whitelist.manage.all" in requesting_permissions 
    can_manage_self = "partners.whitelist.manage.self" in requesting_permissions
    is_managing_self = (partner_id == requesting_partner_id)

    if not ((is_managing_self and can_manage_self) or can_manage_all):
         raise PermissionDeniedError("Permission denied to add IPs for this partner")
         
    # Service handles PartnerNotFound, ConflictError, ValidationError
    created_ip = await service.add_partner_ip(partner_id, ip_data)
    logger.info(f"IP {created_ip.ip_address} added to whitelist for partner {partner_id} by {requesting_partner_id}")
    return success_response(data=created_ip, message="IP address added successfully.")

@router.delete(
    "/{partner_id}/whitelist/{ip_id}", 
    # Standard success response, no data on 204 typically
    response_model=StandardResponse[None], 
    status_code=status.HTTP_200_OK, # Return 200 OK with message
    tags=["Partner IP Whitelist"],
    summary="파트너 IP 화이트리스트에서 IP 제거",
    description="지정된 ID의 IP 항목을 제거합니다.",
    responses={
        status.HTTP_200_OK: {"description": "IP 제거 성공"},
        # Error responses handled globally (401, 403, 404)
    }
)
async def remove_partner_ip(
    # Non-default path args first
    partner_id: UUID = Path(..., description="IP가 속한 파트너 ID"),
    ip_id: UUID = Path(..., description="제거할 IP 항목 ID"),
    # Depends args last
    service: PartnerService = Depends(get_partner_service), 
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    파트너 IP 화이트리스트에서 IP 항목을 제거합니다.
    
    **권한 요구사항:** `whitelist.manage.self` 또는 `whitelist.manage.all`
    """
    can_manage_all = "partners.whitelist.manage.all" in requesting_permissions 
    can_manage_self = "partners.whitelist.manage.self" in requesting_permissions
    is_managing_self = (partner_id == requesting_partner_id)

    if not ((is_managing_self and can_manage_self) or can_manage_all):
        raise PermissionDeniedError("Permission denied to remove IPs for this partner")
        
    # Service handles ResourceNotFoundError 
    success = await service.remove_partner_ip(partner_id, ip_id)
    # if not success:
        # Raise BusinessLogicError if service indicates failure?
        # raise BusinessLogicError("Failed to remove IP address.")
        
    logger.info(f"IP entry {ip_id} removed from whitelist for partner {partner_id} by {requesting_partner_id}")
    return success_response(message="IP address removed successfully.")
    # Or return Response(status_code=status.HTTP_204_NO_CONTENT) 