"""
파트너 리포지토리
파트너, API 키, 설정 등 관련 데이터 액세스
"""
from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from backend.models.domain.partner import Partner, ApiKey, PartnerSetting, PartnerIP

class PartnerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_partner_by_id(self, partner_id: UUID) -> Optional[Partner]:
        """ID로 파트너 조회"""
        result = await self.session.execute(
            select(Partner).where(Partner.id == partner_id)
        )
        return result.scalars().first()
    
    async def get_partner_by_code(self, code: str) -> Optional[Partner]:
        """고유 코드로 파트너 조회"""
        result = await self.session.execute(
            select(Partner).where(Partner.code == code)
        )
        return result.scalars().first()
    
    async def list_partners(
        self, 
        offset: int = 0, 
        limit: int = 100, 
        filters: Dict[str, Any] = None
    ) -> List[Partner]:
        """파트너 목록 조회"""
        query = select(Partner)
        
        # 필터 적용
        if filters:
            if 'status' in filters:
                query = query.where(Partner.status == filters['status'])
            if 'partner_type' in filters:
                query = query.where(Partner.partner_type == filters['partner_type'])
        
        # 정렬 및 페이징
        query = query.order_by(Partner.created_at.desc()).offset(offset).limit(limit)
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def create_partner(self, partner: Partner) -> Partner:
        """새 파트너 생성"""
        self.session.add(partner)
        await self.session.flush()
        return partner
    
    async def update_partner(self, partner: Partner) -> Partner:
        """파트너 정보 업데이트"""
        self.session.add(partner)
        await self.session.flush()
        return partner
    
    async def get_active_api_key(self, key: str) -> Optional[ApiKey]:
        """유효한 API 키 조회"""
        result = await self.session.execute(
            select(ApiKey).where(
                ApiKey.key == key,
                ApiKey.is_active == True
            )
        )
        return result.scalars().first()
    
    async def get_partner_api_keys(self, partner_id: UUID) -> List[ApiKey]:
        """파트너 API 키 목록 조회"""
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.partner_id == partner_id)
        )
        return result.scalars().all()
    
    async def create_api_key(self, api_key: ApiKey) -> ApiKey:
        """새 API 키 생성"""
        self.session.add(api_key)
        await self.session.flush()
        return api_key
    
    async def deactivate_api_key(self, key_id: UUID) -> bool:
        """API 키 비활성화"""
        result = await self.session.execute(
            update(ApiKey)
            .where(ApiKey.id == key_id)
            .values(is_active=False)
        )
        return result.rowcount > 0
    
    async def get_partner_settings(self, partner_id: UUID) -> List[PartnerSetting]:
        """파트너 설정 조회"""
        result = await self.session.execute(
            select(PartnerSetting).where(PartnerSetting.partner_id == partner_id)
        )
        return result.scalars().all()
    
    async def update_partner_setting(self, setting: PartnerSetting) -> PartnerSetting:
        """파트너 설정 업데이트"""
        self.session.add(setting)
        await self.session.flush()
        return setting
    
    async def get_allowed_ips(self, partner_id: UUID) -> List[PartnerIP]:
        """화이트리스트 IP 목록 조회"""
        result = await self.session.execute(
            select(PartnerIP).where(PartnerIP.partner_id == partner_id)
        )
        return result.scalars().all()
    
    async def add_allowed_ip(self, ip: PartnerIP) -> PartnerIP:
        """화이트리스트 IP 추가"""
        self.session.add(ip)
        await self.session.flush()
        return ip
    
    async def remove_allowed_ip(self, ip_id: UUID) -> bool:
        """화이트리스트 IP 삭제"""
        result = await self.session.execute(
            delete(PartnerIP).where(PartnerIP.id == ip_id)
        )
        return result.rowcount > 0