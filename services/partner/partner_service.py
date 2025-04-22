"""
파트너 서비스
파트너 관리, API 키 관리 등 비즈니스 로직 담당
"""
import logging
from uuid import UUID, uuid4
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import secrets
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from backend.models.domain.partner import (
    Partner, ApiKey, PartnerSetting, PartnerIP, 
    PartnerType, PartnerStatus, CommissionModel
)
from backend.repositories.partner_repository import PartnerRepository
from backend.schemas.partner import (
    PartnerCreate, PartnerUpdate, 
    ApiKeyCreate, PartnerSettingCreate, PartnerIPCreate
)
from backend.core.security import create_api_key_secret, hash_api_key

logger = logging.getLogger(__name__)

class PartnerService:
    """파트너 서비스"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.partner_repo = PartnerRepository(db)
    
    async def get_partner(self, partner_id: UUID) -> Optional[Partner]:
        """
        ID로 파트너 조회
        
        Args:
            partner_id: 파트너 ID
            
        Returns:
            Optional[Partner]: 파트너 객체 또는 None
        """
        return await self.partner_repo.get_partner_by_id(partner_id)
    
    async def get_partner_by_code(self, code: str) -> Optional[Partner]:
        """
        코드로 파트너 조회
        
        Args:
            code: 파트너 코드
            
        Returns:
            Optional[Partner]: 파트너 객체 또는 None
        """
        return await self.partner_repo.get_partner_by_code(code)
    
    async def list_partners(
        self, offset: int = 0, limit: int = 100, filters: Dict[str, Any] = None
    ) -> List[Partner]:
        """
        파트너 목록 조회
        
        Args:
            offset: 페이징 오프셋
            limit: 페이징 제한
            filters: 필터
            
        Returns:
            List[Partner]: 파트너 목록
        """
        return await self.partner_repo.list_partners(offset, limit, filters)
    
    async def create_partner(self, partner_data: PartnerCreate) -> Partner:
        """
        새 파트너 생성
        
        Args:
            partner_data: 파트너 생성 데이터
            
        Returns:
            Partner: 생성된 파트너
            
        Raises:
            HTTPException: 코드가 이미 사용 중인 경우
        """
        # 코드 중복 확인
        existing = await self.partner_repo.get_partner_by_code(partner_data.code)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Partner code {partner_data.code} already in use"
            )
        
        # 파트너 객체 생성
        partner = Partner(
            code=partner_data.code,
            name=partner_data.name,
            partner_type=partner_data.partner_type,
            status=partner_data.status,
            commission_model=partner_data.commission_model,
            commission_rate=partner_data.commission_rate,
            contact_name=partner_data.contact_name,
            contact_email=partner_data.contact_email,
            contact_phone=partner_data.contact_phone,
            company_name=partner_data.company_name,
            company_address=partner_data.company_address,
            company_registration_number=partner_data.company_registration_number,
            contract_start_date=partner_data.contract_start_date,
            contract_end_date=partner_data.contract_end_date
        )
        
        # 파트너 저장
        created_partner = await self.partner_repo.create_partner(partner)
        logger.info(f"Created new partner: {partner.code} ({partner.name})")
        
        return created_partner
    
    async def update_partner(
        self, partner_id: UUID, partner_data: PartnerUpdate
    ) -> Optional[Partner]:
        """
        파트너 정보 업데이트
        
        Args:
            partner_id: 파트너 ID
            partner_data: 업데이트 데이터
            
        Returns:
            Optional[Partner]: 업데이트된 파트너 또는 None
            
        Raises:
            HTTPException: 파트너가 존재하지 않는 경우
        """
        # 파트너 조회
        partner = await self.partner_repo.get_partner_by_id(partner_id)
        if not partner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Partner {partner_id} not found"
            )
        
        # 필드 업데이트
        for key, value in partner_data.dict(exclude_unset=True).items():
            setattr(partner, key, value)
        
        # 파트너 저장
        updated_partner = await self.partner_repo.update_partner(partner)
        logger.info(f"Updated partner: {partner.code} ({partner.name})")
        
        return updated_partner
    
    async def create_api_key(
        self, partner_id: UUID, api_key_data: ApiKeyCreate
    ) -> Dict[str, Any]:
        """
        새 API 키 생성
        
        Args:
            partner_id: 파트너 ID
            api_key_data: API 키 생성 데이터
            
        Returns:
            Dict[str, Any]: API 키 및 비밀키
            
        Raises:
            HTTPException: 파트너가 존재하지 않는 경우
        """
        # 파트너 조회
        partner = await self.partner_repo.get_partner_by_id(partner_id)
        if not partner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Partner {partner_id} not found"
            )
        
        # API 키 및 비밀키 생성
        key, key_secret = create_api_key_secret()
        key_hash = hash_api_key(key)
        
        # API 키 객체 생성
        api_key = ApiKey(
            partner_id=partner_id,
            key=key_hash,
            name=api_key_data.name,
            permissions=api_key_data.permissions,
            is_active=True,
            expires_at=api_key_data.expires_at
        )
        
        # API 키 저장
        created_key = await self.partner_repo.create_api_key(api_key)
        logger.info(f"Created new API key for partner {partner.code}: {api_key_data.name}")
        
        # 응답 데이터 생성
        # 주의: 이 때만 secret을 반환하고 이후로는
        # DB에 저장하거나 반환하지 않음
        return {
            "id": created_key.id,
            "key": key,  # 원본 키
            "key_secret": key_secret,  # 비밀키
            "partner_id": partner_id,
            "name": created_key.name,
            "permissions": created_key.permissions,
            "is_active": created_key.is_active,
            "expires_at": created_key.expires_at,
            "created_at": created_key.created_at
        }
    
    async def deactivate_api_key(self, key_id: UUID) -> bool:
        """
        API 키 비활성화
        
        Args:
            key_id: API 키 ID
            
        Returns:
            bool: 성공 여부
        """
        result = await self.partner_repo.deactivate_api_key(key_id)
        if result:
            logger.info(f"Deactivated API key: {key_id}")
        return result
    
    async def get_partner_api_keys(self, partner_id: UUID) -> List[ApiKey]:
        """
        파트너 API 키 목록 조회
        
        Args:
            partner_id: 파트너 ID
            
        Returns:
            List[ApiKey]: API 키 목록
        """
        return await self.partner_repo.get_partner_api_keys(partner_id)
    
    async def validate_api_key(self, key: str) -> Optional[ApiKey]:
        """
        API 키 유효성 검증
        
        Args:
            key: API 키
            
        Returns:
            Optional[ApiKey]: 유효한 API 키 객체 또는 None
        """
        # 키 해싱
        key_hash = hash_api_key(key)
        
        # 유효한 API 키 조회
        api_key = await self.partner_repo.get_active_api_key(key_hash)
        
        if not api_key:
            return None
        
        # 만료 확인
        if api_key.expires_at and api_key.expires_at <= datetime.utcnow():
            return None
        
        # 사용 시간 업데이트
        api_key.last_used_at = datetime.utcnow()
        await self.db.flush()
        
        return api_key
    
    async def update_partner_setting(
        self, partner_id: UUID, setting_data: PartnerSettingCreate
    ) -> PartnerSetting:
        """
        파트너 설정 업데이트
        
        Args:
            partner_id: 파트너 ID
            setting_data: 설정 데이터
            
        Returns:
            PartnerSetting: 업데이트된 설정
            
        Raises:
            HTTPException: 파트너가 존재하지 않는 경우
        """
        # 파트너 조회
        partner = await self.partner_repo.get_partner_by_id(partner_id)
        if not partner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Partner {partner_id} not found"
            )
        
        # 기존 설정 조회
        settings = await self.partner_repo.get_partner_settings(partner_id)
        existing = next((s for s in settings if s.key == setting_data.key), None)
        
        if existing:
            # 기존 설정 업데이트
            existing.value = setting_data.value
            if setting_data.description:
                existing.description = setting_data.description
            setting = await self.partner_repo.update_partner_setting(existing)
        else:
            # 새 설정 생성
            setting = PartnerSetting(
                partner_id=partner_id,
                key=setting_data.key,
                value=setting_data.value,
                description=setting_data.description
            )
            setting = await self.partner_repo.update_partner_setting(setting)
        
        logger.info(f"Updated setting for partner {partner.code}: {setting_data.key}")
        
        return setting
    
    async def get_partner_settings(self, partner_id: UUID) -> List[PartnerSetting]:
        """
        파트너 설정 목록 조회
        
        Args:
            partner_id: 파트너 ID
            
        Returns:
            List[PartnerSetting]: 설정 목록
        """
        return await self.partner_repo.get_partner_settings(partner_id)
    
    async def add_allowed_ip(
        self, partner_id: UUID, ip_data: PartnerIPCreate
    ) -> PartnerIP:
        """
        허용 IP 추가
        
        Args:
            partner_id: 파트너 ID
            ip_data: IP 데이터
            
        Returns:
            PartnerIP: 추가된 IP
            
        Raises:
            HTTPException: 파트너가 존재하지 않는 경우
        """
        # 파트너 조회
        partner = await self.partner_repo.get_partner_by_id(partner_id)
        if not partner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Partner {partner_id} not found"
            )
        
        # IP 객체 생성
        ip = PartnerIP(
            partner_id=partner_id,
            ip_address=ip_data.ip_address,
            description=ip_data.description
        )
        
        # IP 저장
        added_ip = await self.partner_repo.add_allowed_ip(ip)
        logger.info(f"Added allowed IP for partner {partner.code}: {ip_data.ip_address}")
        
        return added_ip
    
    async def remove_allowed_ip(self, ip_id: UUID) -> bool:
        """
        허용 IP 제거
        
        Args:
            ip_id: IP ID
            
        Returns:
            bool: 성공 여부
        """
        result = await self.partner_repo.remove_allowed_ip(ip_id)
        if result:
            logger.info(f"Removed allowed IP: {ip_id}")
        return result
    
    async def get_allowed_ips(self, partner_id: UUID) -> List[PartnerIP]:
        """
        허용 IP 목록 조회
        
        Args:
            partner_id: 파트너 ID
            
        Returns:
            List[PartnerIP]: IP 목록
        """
        return await self.partner_repo.get_allowed_ips(partner_id)
    
    async def check_ip_allowed(self, partner_id: UUID, ip_address: str) -> bool:
        """
        IP 허용 여부 확인
        
        Args:
            partner_id: 파트너 ID
            ip_address: IP 주소
            
        Returns:
            bool: 허용 여부
        """
        # 파트너의 허용 IP 목록 조회
        allowed_ips = await self.partner_repo.get_allowed_ips(partner_id)
        
        # IP가 목록에 있는지 확인
        return any(ip.ip_address == ip_address for ip in allowed_ips)