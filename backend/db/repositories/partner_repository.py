"""
파트너 리포지토리
파트너, API 키, 설정 등 관련 데이터 액세스
"""
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, and_, or_, desc
import logging

from backend.partners.models import Partner, ApiKey, PartnerIP

logger = logging.getLogger(__name__)

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
        skip: int = 0, 
        limit: int = 100, 
        filters: Optional[Dict[str, Any]] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = "asc"
    ) -> Tuple[List[Partner], int]:
        """파트너 목록 조회"""
        # 기본 쿼리 구성
        query = select(Partner)
        count_query = select(func.count(Partner.id))
        
        # 필터 적용
        if filters:
            if filters.get('name'):
                name_filter = f"%{filters['name']}%"
                query = query.where(Partner.name.ilike(name_filter))
                count_query = count_query.where(Partner.name.ilike(name_filter))
            
            if filters.get('status'):
                query = query.where(Partner.status == filters['status'])
                count_query = count_query.where(Partner.status == filters['status'])
            
            if filters.get('partner_type'):
                query = query.where(Partner.partner_type == filters['partner_type'])
                count_query = count_query.where(Partner.partner_type == filters['partner_type'])
        
        # 정렬 적용
        if sort_by:
            column = getattr(Partner, sort_by, Partner.created_at)
            if sort_order.lower() == "desc":
                query = query.order_by(desc(column))
            else:
                query = query.order_by(column)
        else:
            # 기본 정렬: 생성일 내림차순
            query = query.order_by(desc(Partner.created_at))
        
        # 페이징 적용
        query = query.offset(skip).limit(limit)
        
        # 쿼리 실행
        result = await self.session.execute(query)
        partners = result.scalars().all()
        
        # 전체 개수 조회
        count_result = await self.session.execute(count_query)
        total_count = count_result.scalar()
        
        return list(partners), total_count
    
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
    
    async def get_active_api_key(self, key_hash: str) -> Optional[ApiKey]:
        """해시로 유효한 API 키 조회"""
        result = await self.session.execute(
            select(ApiKey).where(
                ApiKey.key == key_hash,
                ApiKey.is_active == True
            )
        )
        return result.scalars().first()
    
    async def get_active_api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        """해시로 유효한 API 키 조회 (get_active_api_key의 별칭)"""
        return await self.get_active_api_key(key_hash)
    
    async def get_api_key_by_id(self, key_id: UUID) -> Optional[ApiKey]:
        """ID로 API 키 조회"""
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.id == key_id)
        )
        return result.scalars().first()
    
    async def get_partner_api_keys(
        self, 
        partner_id: UUID,
        include_inactive: bool = False
    ) -> List[ApiKey]:
        """파트너 API 키 목록 조회"""
        query = select(ApiKey).where(ApiKey.partner_id == partner_id)
        
        if not include_inactive:
            query = query.where(ApiKey.is_active == True)
            
        query = query.order_by(desc(ApiKey.created_at))
        
        result = await self.session.execute(query)
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
            .returning(ApiKey.id)
        )
        
        updated = result.scalar()
        await self.session.flush()
        
        return updated is not None
    
    async def update_api_key_last_used(self, api_key: ApiKey, ip_address: Optional[str] = None) -> None:
        """API 키 마지막 사용 정보 업데이트"""
        api_key.last_used_at = datetime.utcnow()
        
        if ip_address:
            api_key.last_used_ip = ip_address
            
        self.session.add(api_key)
        await self.session.flush()
    
    # --- 주석 처리 시작: PartnerSetting 관련 메서드들 ---
    # async def get_partner_settings(self, partner_id: UUID) -> List[PartnerSetting]:
    #     """파트너 설정 목록 조회"""
    #     result = await self.session.execute(
    #         select(PartnerSetting).where(PartnerSetting.partner_id == partner_id)
    #     )
    #     return result.scalars().all()

    # async def get_partner_setting(self, partner_id: UUID, key: str) -> Optional[PartnerSetting]: # Around Line 193
    #     """특정 파트너 설정 조회"""
    #     result = await self.session.execute(
    #         select(PartnerSetting).where(
    #             PartnerSetting.partner_id == partner_id,
    #             PartnerSetting.key == key
    #         )
    #     )
    #     return result.scalars().first()
    
    # async def create_or_update_partner_setting(self, setting: PartnerSetting) -> PartnerSetting: # Around Line 202
    #     """파트너 설정 생성 또는 업데이트"""
    #     # 기존 설정 확인
    #     existing = await self.get_partner_setting(setting.partner_id, setting.key)
    #     
    #     if existing:
    #         # 값 업데이트
    #         existing.value = setting.value
    #         if setting.description:
    #             existing.description = setting.description
    #         self.session.add(existing)
    #         await self.session.flush()
    #         return existing
    #     else:
    #         # 새로 생성
    #         self.session.add(setting)
    #         await self.session.flush()
    #         return setting
    
    # async def delete_partner_setting(self, partner_id: UUID, key: str) -> bool: # Around Line 221
    #     """파트너 설정 삭제"""
    #     result = await self.session.execute(
    #         delete(PartnerSetting).where(
    #             PartnerSetting.partner_id == partner_id,
    #             PartnerSetting.key == key
    #         )
    #         .returning(PartnerSetting.id)
    #     )
    #     
    #     deleted = result.scalar()
    #     await self.session.flush()
    #     
    #     return deleted is not None
    # --- 주석 처리 끝 ---    

    async def get_allowed_ips(self, partner_id: UUID) -> List[PartnerIP]:
        """파트너 허용 IP 목록 조회"""
        result = await self.session.execute(
            select(PartnerIP).where(
                PartnerIP.partner_id == partner_id,
                PartnerIP.is_active == True
            )
        )
        return result.scalars().all()
    
    # --- 주석 처리 시작: PartnerIP 관련 메서드들 (PartnerIP도 정의되지 않았을 수 있음) ---
    # async def get_partner_ip(self, ip_id: UUID) -> Optional[PartnerIP]:
    #     """ID로 파트너 IP 조회"""
    #     result = await self.session.execute(
    #         select(PartnerIP).where(PartnerIP.id == ip_id)
    #     )
    #     return result.scalars().first()
    
    # async def get_partner_ip_by_address(self, partner_id: UUID, ip_address: str) -> Optional[PartnerIP]:
    #     """특정 IP 주소로 파트너 IP 조회"""
    #     # ... implementation ...

    # async def add_allowed_ip(self, ip: PartnerIP) -> PartnerIP:
    #     """파트너 허용 IP 추가"""
    #     # ... implementation ...

    # async def remove_allowed_ip(self, ip_id: UUID) -> bool:
    #     """파트너 허용 IP 삭제"""
    #     # ... implementation ...
    # --- 주석 처리 끝 ---    

    async def get_api_key_owner(self, key_id: UUID) -> Optional[UUID]:
        """API 키 ID로 파트너 ID 조회"""
        result = await self.session.execute(
            select(ApiKey.partner_id).where(ApiKey.id == key_id)
        )
        return result.scalar()
    
    async def get_ip_owner(self, ip_id: UUID) -> Optional[UUID]:
        """IP ID로 파트너 ID 조회"""
        result = await self.session.execute(
            select(PartnerIP.partner_id).where(PartnerIP.id == ip_id)
        )
        return result.scalar()