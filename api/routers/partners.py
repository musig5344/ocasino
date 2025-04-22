from fastapi import APIRouter, Depends, Body, Query, Path, status
from sqlalchemy.orm import Session
from typing import Optional, List
import logging

from backend.api.dependencies.db import get_db
from backend.api.dependencies.auth import get_current_partner_id, verify_permissions
from backend.api.dependencies.common import common_pagination_params, common_sort_params
from backend.models.schemas.partner import (
    PartnerCreate, PartnerUpdate, PartnerResponse, PartnerList,
    PartnerConfigUpdate, PartnerConfigResponse,
    PartnerContactCreate, PartnerContactResponse, PartnerContactList
)
from backend.services.partner.partner_service import PartnerService
from backend.api.errors.exceptions import ResourceNotFoundException, ForbiddenException, DuplicateResourceException

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("", response_model=PartnerResponse, status_code=status.HTTP_201_CREATED)
async def create_partner(
    partner_data: PartnerCreate,
    db: Session = Depends(get_db),
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
    try:
        partner = await partner_service.create_partner(partner_data)
    except ValueError as e:
        raise DuplicateResourceException("Partner", str(e))
    
    logger.info(f"New partner created: {partner.id} ({partner.name})")
    
    return PartnerResponse(
        id=partner.id,
        name=partner.name,
        api_url=partner.api_url,
        status=partner.status,
        integration_type=partner.integration_type,
        created_at=partner.created_at,
        updated_at=partner.updated_at,
        config=PartnerConfigResponse(
            id=partner.config.id,
            partner_id=partner.id,
            fee_model=partner.config.fee_model,
            fee_percentage=partner.config.fee_percentage,
            monthly_fee=partner.config.monthly_fee,
            transaction_fee=partner.config.transaction_fee,
            allowed_currencies=partner.config.allowed_currencies,
            max_transaction_amount=partner.config.max_transaction_amount,
            created_at=partner.config.created_at,
            updated_at=partner.config.updated_at
        ) if partner.config else None
    )

@router.get("", response_model=PartnerList)
async def list_partners(
    name: Optional[str] = Query(None, description="이름으로 필터링"),
    status: Optional[str] = Query(None, description="상태로 필터링 (active, inactive, suspended)"),
    integration_type: Optional[str] = Query(None, description="통합 유형으로 필터링"),
    pagination: dict = Depends(common_pagination_params),
    sorting: dict = Depends(common_sort_params),
    db: Session = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너 목록 조회
    
    관리자는 모든 파트너를 볼 수 있지만, 일반 파트너는 자신의 정보만 볼 수 있습니다.
    """
    partner_service = PartnerService(db)
    
    # 권한 확인
    try:
        # 관리자 권한 확인
        await verify_permissions("partners.read")
        # 관리자는 모든 파트너 조회 가능
        filter_by_id = None
    except:
        # 일반 파트너는 자신의 정보만 조회 가능
        filter_by_id = current_partner_id
    
    # 파트너 목록 조회
    partners, total = await partner_service.list_partners(
        skip=pagination["skip"],
        limit=pagination["limit"],
        name=name,
        status=status,
        integration_type=integration_type,
        filter_by_id=filter_by_id,
        sort_by=sorting["sort_by"],
        sort_order=sorting["sort_order"]
    )
    
    # 응답 생성
    items = []
    for partner in partners:
        items.append(PartnerResponse(
            id=partner.id,
            name=partner.name,
            api_url=partner.api_url,
            status=partner.status,
            integration_type=partner.integration_type,
            created_at=partner.created_at,
            updated_at=partner.updated_at,
            config=PartnerConfigResponse(
                id=partner.config.id,
                partner_id=partner.id,
                fee_model=partner.config.fee_model,
                fee_percentage=partner.config.fee_percentage,
                monthly_fee=partner.config.monthly_fee,
                transaction_fee=partner.config.transaction_fee,
                allowed_currencies=partner.config.allowed_currencies,
                max_transaction_amount=partner.config.max_transaction_amount,
                created_at=partner.config.created_at,
                updated_at=partner.config.updated_at
            ) if partner.config else None
        ))
    
    return PartnerList(
        items=items,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"]
    )

@router.get("/{partner_id}", response_model=PartnerResponse)
async def get_partner(
    partner_id: str = Path(..., description="파트너 ID"),
    db: Session = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너 세부 정보 조회
    
    파트너는 자신의 정보만 볼 수 있습니다.
    관리자는 모든 파트너 정보를 볼 수 있습니다.
    """
    # 권한 확인
    if partner_id != current_partner_id:
        # 관리자 권한 확인
        try:
            await verify_permissions("partners.read")
        except:
            raise ForbiddenException("You can only view your own partner information")
    
    partner_service = PartnerService(db)
    
    # 파트너 조회
    partner = await partner_service.get_partner(partner_id)
    if not partner:
        raise ResourceNotFoundException("Partner", partner_id)
    
    return PartnerResponse(
        id=partner.id,
        name=partner.name,
        api_url=partner.api_url,
        status=partner.status,
        integration_type=partner.integration_type,
        created_at=partner.created_at,
        updated_at=partner.updated_at,
        config=PartnerConfigResponse(
            id=partner.config.id,
            partner_id=partner.id,
            fee_model=partner.config.fee_model,
            fee_percentage=partner.config.fee_percentage,
            monthly_fee=partner.config.monthly_fee,
            transaction_fee=partner.config.transaction_fee,
            allowed_currencies=partner.config.allowed_currencies,
            max_transaction_amount=partner.config.max_transaction_amount,
            created_at=partner.config.created_at,
            updated_at=partner.config.updated_at
        ) if partner.config else None
    )

@router.put("/{partner_id}", response_model=PartnerResponse)
async def update_partner(
    partner_data: PartnerUpdate,
    partner_id: str = Path(..., description="파트너 ID"),
    db: Session = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너 정보 업데이트
    
    파트너는 자신의 일부 정보만 업데이트할 수 있습니다.
    관리자는 모든 파트너 정보를 업데이트할 수 있습니다.
    """
    partner_service = PartnerService(db)
    
    # 권한에 따라 업데이트 가능한 필드 제한
    if partner_id != current_partner_id:
        # 관리자 권한 확인
        try:
            await verify_permissions("partners.update")
        except:
            raise ForbiddenException("You can only update your own partner information")
    else:
        # 일반 파트너는 제한된 필드만 업데이트 가능
        restricted_fields = ["status", "integration_type"]
        for field in restricted_fields:
            if getattr(partner_data, field, None) is not None:
                raise ForbiddenException(f"You cannot update the {field} field")
    
    # 파트너 업데이트
    partner = await partner_service.update_partner(partner_id, partner_data)
    if not partner:
        raise ResourceNotFoundException("Partner", partner_id)
    
    logger.info(f"Partner updated: {partner.id} ({partner.name})")
    
    return PartnerResponse(
        id=partner.id,
        name=partner.name,
        api_url=partner.api_url,
        status=partner.status,
        integration_type=partner.integration_type,
        created_at=partner.created_at,
        updated_at=partner.updated_at,
        config=PartnerConfigResponse(
            id=partner.config.id,
            partner_id=partner.id,
            fee_model=partner.config.fee_model,
            fee_percentage=partner.config.fee_percentage,
            monthly_fee=partner.config.monthly_fee,
            transaction_fee=partner.config.transaction_fee,
            allowed_currencies=partner.config.allowed_currencies,
            max_transaction_amount=partner.config.max_transaction_amount,
            created_at=partner.config.created_at,
            updated_at=partner.config.updated_at
        ) if partner.config else None
    )

@router.put("/{partner_id}/config", response_model=PartnerConfigResponse)
async def update_partner_config(
    config_data: PartnerConfigUpdate,
    partner_id: str = Path(..., description="파트너 ID"),
    db: Session = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너 구성 업데이트
    
    관리자 권한이 필요합니다.
    """
    # 관리자 권한 확인
    await verify_permissions("partners.config.update")
    
    partner_service = PartnerService(db)
    
    # 파트너 구성 업데이트
    config = await partner_service.update_partner_config(partner_id, config_data)
    if not config:
        raise ResourceNotFoundException("Partner", partner_id)
    
    logger.info(f"Partner config updated: {partner_id}")
    
    return PartnerConfigResponse(
        id=config.id,
        partner_id=config.partner_id,
        fee_model=config.fee_model,
        fee_percentage=config.fee_percentage,
        monthly_fee=config.monthly_fee,
        transaction_fee=config.transaction_fee,
        allowed_currencies=config.allowed_currencies,
        max_transaction_amount=config.max_transaction_amount,
        created_at=config.created_at,
        updated_at=config.updated_at
    )

@router.post("/{partner_id}/contacts", response_model=PartnerContactResponse, status_code=status.HTTP_201_CREATED)
async def create_partner_contact(
    contact_data: PartnerContactCreate,
    partner_id: str = Path(..., description="파트너 ID"),
    db: Session = Depends(get_db),
    current_partner_id: str = Depends(get_current_partner_id)
):
    """
    파트너 연락처 생성
    
    파트너는 자신의 연락처만 생성할 수 있습니다.
    관리자는 모든 파트너의 연락처를 생성할 수 있습니다.
    """
    # 권한 확인
    if partner_id != current_partner_id:
        # 관리자 권한 확인
        try:
            await verify_permissions("partners.contacts.manage")
        except:
            raise ForbiddenException("You can only manage your own contacts")
    
    partner_service = PartnerService(db)
    
    # 연락처 생성
    contact = await partner_service.create_partner_contact(partner_id, contact_data)
    if not contact:
        raise ResourceNotFoundException("Partner", partner_id)
    
    logger.info(f"Partner contact created: {contact.id} for partner {partner_id}")
    
    return PartnerContactResponse(
        id=contact.id,
        partner_id=contact.partner_id,
        name=contact.name,
        email=contact.email,
        phone=contact.phone,
        role=contact.role,
        is_primary=contact.is_primary,
        created_at=contact.created_at,
        updated_at=contact.updated_at
    )