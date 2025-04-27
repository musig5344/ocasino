"""
파트너 데이터 접근 로직 (Repository)
"""
import logging
from typing import Optional, List, Dict, Any, Tuple
from uuid import UUID

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload # For loading related objects

# --- Updated Import --- 
from backend.core.repository import BaseRepository # Import BaseRepository
from backend.partners.models import (
    Partner as PartnerModel, ApiKey as ApiKeyModel,
    PartnerSetting as PartnerSettingModel, PartnerIP as PartnerIPModel
)

logger = logging.getLogger(__name__)

class PartnerRepository(BaseRepository[PartnerModel]):
    """파트너 및 관련 엔티티에 대한 데이터베이스 작업을 처리합니다."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(session, PartnerModel)
        # self.db is now the session via BaseRepository
        
    # get_partner_by_id is replaced by BaseRepository.find_one
    # Example usage: await self.find_one(filters={"id": partner_id}, load_relations=["api_keys", "settings"]) 

    async def get_partner_by_code(self, partner_code: str) -> Optional[PartnerModel]:
        """파트너 코드로 파트너 정보를 조회합니다."""
        stmt = select(PartnerModel).where(PartnerModel.code == partner_code)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
        
    async def get_partner_by_email(self, email: str) -> Optional[PartnerModel]:
        """파트너 연락처 이메일로 파트너 정보를 조회합니다."""
        stmt = select(PartnerModel).where(PartnerModel.contact_email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # list_partners is replaced by BaseRepository.find_many and BaseRepository.count
    # Service layer (_find_many) should call:
    # items = await self.find_many(skip=skip, limit=limit, filters=filters, sort_by=sort_by, sort_order=sort_order)
    # total = await self.count(filters=filters)
    # async def list_partners(
    #     self, skip: int = 0, limit: int = 100, 
    #     filters: Optional[Dict[str, Any]] = None, 
    #     sort_by: Optional[str] = None, 
    #     sort_order: str = 'asc'
    # ) -> Tuple[List[PartnerModel], int]:
    #     """파트너 목록을 필터링하고 정렬하여 조회합니다."""
    #     stmt = select(PartnerModel)
    #     count_stmt = select(func.count()).select_from(PartnerModel)
    # 
    #     if filters:
    #         for key, value in filters.items():
    #             if hasattr(PartnerModel, key):
    #                 column = getattr(PartnerModel, key)
    #                 # BaseRepository._apply_filters handles more operators now
    #                 if '__icontains' in key: 
    #                     actual_key = key.replace('__icontains', '')
    #                     column = getattr(PartnerModel, actual_key)
    #                     stmt = stmt.where(column.ilike(f'%{value}%'))
    #                     count_stmt = count_stmt.where(column.ilike(f'%{value}%'))
    #                 else:
    #                     stmt = stmt.where(column == value)
    #                     count_stmt = count_stmt.where(column == value)
    #     
    #     # Get total count before sorting and pagination
    #     total_result = await self.db.execute(count_stmt) # Use self.db
    #     total = total_result.scalar_one()
    # 
    #     # Apply sorting
    #     if sort_by and hasattr(PartnerModel, sort_by):
    #         order_column = getattr(PartnerModel, sort_by)
    #         if sort_order.lower() == 'desc':
    #             stmt = stmt.order_by(order_column.desc())
    #         else:
    #             stmt = stmt.order_by(order_column.asc())
    #     else:
    #          stmt = stmt.order_by(PartnerModel.created_at.asc()) # Default sort
    #          
    #     # Apply pagination
    #     stmt = stmt.offset(skip).limit(limit)
    #     
    #     result = await self.db.execute(stmt) # Use self.db
    #     partners = result.scalars().all()
    #     return partners, total

    # create_partner is replaced by BaseRepository.create
    # Example usage in Service._create_entity: 
    #   # Service creates the model instance first
    #   new_partner = self.model_class(**data)
    #   # Then calls the base repository create method
    #   created_partner = await self.repository.create(new_partner.__dict__) # Pass data dict
    #   return created_partner
    # Note: Ensure BaseRepository.create handles dict data correctly.
    # async def create_partner(self, partner: PartnerModel) -> PartnerModel:
    #     """새 파트너를 데이터베이스에 추가합니다."""
    #     self.db.add(partner) # Use self.db
    #     await self.db.flush() # Flush to get ID or handle potential errors
    #     await self.db.refresh(partner) # Refresh to get defaults/triggers
    #     return partner
        
    # update_partner is replaced by BaseRepository.update
    # Example usage in Service._update_entity: 
    #   # Service finds entity, validates data, then calls repo update by ID
    #   updated_partner = await self.repository.update(entity.id, data)
    #   return updated_partner
    # Note: BaseRepository.update finds the partner by ID first.
    # async def update_partner(self, partner: PartnerModel, update_data: Dict[str, Any]) -> PartnerModel:
    #     """기존 파트너 정보를 업데이트합니다."""
    #     for key, value in update_data.items():
    #         if hasattr(partner, key):
    #             setattr(partner, key, value)
    #         else:
    #              logger.warning(f"Attempted to update non-existent attribute '{key}' on Partner {partner.id}")
    #     
    #     await self.db.flush() # Use self.db
    #     await self.db.refresh(partner)
    #     return partner
        
    # delete_partner (hard delete) is replaced by BaseRepository.delete(id, soft_delete=False)
    # Note: PartnerService uses soft delete via _delete_entity, which calls self.update(entity.id, soft_delete_data).
    # If a hard delete is ever needed, use self.delete(id, soft_delete=False).
    # async def delete_partner(self, partner: PartnerModel) -> bool:
    #     """파트너를 데이터베이스에서 삭제합니다 (Hard Delete)."""
    #     await self.db.delete(partner) # Use self.db
    #     await self.db.flush()
    #     return True # Assume success if no exception

    # --- API Key Repository Methods --- 

    async def create_api_key(self, api_key: ApiKeyModel) -> ApiKeyModel:
        self.db.add(api_key)
        await self.db.flush()
        await self.db.refresh(api_key)
        return api_key
        
    async def get_api_key_by_id(self, key_id: UUID) -> Optional[ApiKeyModel]:
        stmt = select(ApiKeyModel).where(ApiKeyModel.id == key_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
        
    async def get_api_key_by_key(self, key_str: str) -> Optional[ApiKeyModel]:
        stmt = select(ApiKeyModel).where(ApiKeyModel.key == key_str)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
        
    async def get_api_keys_by_partner(self, partner_id: UUID, active_only: bool = True) -> List[ApiKeyModel]:
        stmt = select(ApiKeyModel).where(ApiKeyModel.partner_id == partner_id)
        if active_only:
            stmt = stmt.where(ApiKeyModel.is_active == True)
        result = await self.db.execute(stmt)
        return result.scalars().all()
        
    async def update_api_key(self, api_key: ApiKeyModel, update_data: Dict[str, Any]) -> bool:
        for key, value in update_data.items():
            if hasattr(api_key, key):
                setattr(api_key, key, value)
        await self.db.flush()
        return True
        
    # --- Partner Setting Repository Methods --- 

    async def create_partner_setting(self, setting: PartnerSettingModel) -> PartnerSettingModel:
        self.db.add(setting)
        await self.db.flush()
        await self.db.refresh(setting)
        return setting
        
    async def get_partner_setting(self, partner_id: UUID, key: str) -> Optional[PartnerSettingModel]:
        stmt = select(PartnerSettingModel).where(
            PartnerSettingModel.partner_id == partner_id, 
            PartnerSettingModel.setting_key == key
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
        
    async def get_partner_settings_by_partner(self, partner_id: UUID) -> List[PartnerSettingModel]:
        stmt = select(PartnerSettingModel).where(PartnerSettingModel.partner_id == partner_id)
        result = await self.db.execute(stmt)
        return result.scalars().all()
        
    async def update_partner_setting(self, setting: PartnerSettingModel, update_data: Dict[str, Any]) -> PartnerSettingModel:
        for key, value in update_data.items():
            if hasattr(setting, key):
                setattr(setting, key, value)
        await self.db.flush()
        await self.db.refresh(setting)
        return setting
        
    # --- Partner IP Whitelist Repository Methods --- 

    async def create_partner_ip(self, ip_entry: PartnerIPModel) -> PartnerIPModel:
        self.db.add(ip_entry)
        await self.db.flush()
        await self.db.refresh(ip_entry)
        return ip_entry
        
    async def get_partner_ip_by_id(self, ip_id: UUID) -> Optional[PartnerIPModel]:
        stmt = select(PartnerIPModel).where(PartnerIPModel.id == ip_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
        
    async def get_partner_ip_by_address(self, partner_id: UUID, ip_address: str) -> Optional[PartnerIPModel]:
        stmt = select(PartnerIPModel).where(
            PartnerIPModel.partner_id == partner_id, 
            PartnerIPModel.ip_address == ip_address
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
        
    async def get_partner_ips_by_partner(self, partner_id: UUID, active_only: bool = True) -> List[PartnerIPModel]:
        stmt = select(PartnerIPModel).where(PartnerIPModel.partner_id == partner_id)
        if active_only:
            stmt = stmt.where(PartnerIPModel.is_active == True)
        result = await self.db.execute(stmt)
        return result.scalars().all()
        
    async def delete_partner_ip(self, ip_entry: PartnerIPModel) -> bool:
        await self.db.delete(ip_entry)
        await self.db.flush()
        return True

    # Add update_partner_ip if soft delete is needed
    # async def update_partner_ip(self, ip_entry: PartnerIPModel, update_data: Dict[str, Any]) -> bool:
    #     ... 