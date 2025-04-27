"""
파트너 서비스
파트너 관리, API 키 관리 등 비즈니스 로직 담당
"""
import logging
from uuid import UUID, uuid4
from typing import Optional, List, Dict, Any, Tuple, Union
from datetime import datetime, timedelta
import secrets
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

# --- Updated Imports --- 
from backend.partners.models import (
    Partner as PartnerModel, ApiKey as ApiKeyModel, 
    PartnerSetting as PartnerSettingModel, PartnerIP as PartnerIPModel,
    PartnerStatus # Assuming PartnerStatus enum is defined within models.py or imported there
)
from backend.partners.repository import PartnerRepository
from backend.partners.schemas import (
    PartnerCreate, PartnerUpdate, 
    ApiKeyCreate, PartnerSettingCreate, PartnerIPCreate,
    Partner, ApiKey, PartnerSetting, PartnerIP, # BaseService에서 사용할 Partner 스키마
    Partner as PartnerSchema # 명확성을 위해 PartnerSchema 로 alias 사용 가능
)
from backend.core.security import generate_api_secret, get_password_hash, verify_password
from backend.core.exceptions import (
    PartnerAlreadyExistsError, PartnerNotFoundError, InvalidInputError,
    APIKeyGenerationError, DatabaseError, AuthorizationError, ConflictError, 
    NotFoundError # Replace ResourceNotFoundError with NotFoundError
    # ResourceNotFoundError # PartnerNotFoundError 가 이미 있으므로 없어도 될 수 있음
)
from backend.utils.permissions import check_permission # Keep utils import as is unless moved
# from backend.cache.redis_cache import RedisCache, cache_result # Keep commented if not used yet

# Import BaseService
from backend.core.service import BaseService

logger = logging.getLogger(__name__)

def get_model_dict(model):
    """Pydantic v1/v2 호환 사전 변환 함수 (BaseService에서 model_dump 사용으로 대체 가능성 있음)"""
    if hasattr(model, 'model_dump'):
        return model.model_dump(exclude_unset=True)
    elif hasattr(model, 'dict'):
        return model.dict(exclude_unset=True)
    else:
        return {k: getattr(model, k) for k in dir(model)
                if not k.startswith('_') and not callable(getattr(model, k))}

class PartnerService(BaseService[PartnerModel, PartnerSchema, PartnerCreate, PartnerUpdate]):
    """파트너 관련 비즈니스 로직 (BaseService 상속)"""
    
    # Override BaseService class attributes
    service_name = "partner"
    entity_name = "partner"
    not_found_exception_class = PartnerNotFoundError
    # id_field = "id" # 기본값이 id 이므로 생략 가능
    
    def __init__(self, db: AsyncSession = None, partner_repo: PartnerRepository = None):
        # Initialize BaseService first
        super().__init__(
            db=db,
            model_class=PartnerModel,            # DB Model
            response_schema_class=PartnerSchema, # Response Schema (Partner)
            create_schema_class=PartnerCreate,   # Create Schema
            update_schema_class=PartnerUpdate    # Update Schema
        )
        # Inject or create repository
        self.partner_repo = partner_repo or (PartnerRepository(db) if db else None)
        if not self.partner_repo:
             logger.error("PartnerRepository could not be initialized in PartnerService.")
             # 혹은 raise Exception? 서비스 초기화 실패는 심각할 수 있음
             # raise ValueError("Database session is required to initialize PartnerRepository")
             
        logger.debug("PartnerService initialized with PartnerRepository.")

    # Remove _get_partner_or_404 as BaseService provides get_or_404
    # async def _get_partner_or_404(self, partner_id: UUID) -> PartnerModel:
    #     """파트너를 찾거나 404 에러 발생"""
    #     partner = await self.partner_repo.get_partner_by_id(partner_id)
    #     if not partner:
    #         logger.warning(f"Partner not found: {partner_id}")
    #         raise self.not_found_exception_class(partner_id=str(partner_id)) # Use class attribute
    #     return partner
        
    # --- Partner CRUD (이제 BaseService 메소드를 사용하거나 오버라이드) --- 

    # get 메소드는 BaseService 것을 그대로 사용 가능 (get -> get_or_404 -> _find_one 호출)
    # @cache_result(key_prefix="partner", ttl=3600) # Caching example - 필요시 BaseService에 적용하거나 여기서 오버라이드
    # async def get_partner(self, partner_id: UUID) -> PartnerModel:
    #     """ID로 파트너 조회"""
    #     return await self.get_or_404(partner_id)

    # list 메소드는 BaseService 것을 사용 -> _find_many 구현 필요
    # async def list(self, skip: int = 0, limit: int = 100, 
    #               filters: Optional[Dict[str, Any]] = None, 
    #               sort_by: Optional[str] = None, 
    #               sort_order: str = 'asc'
    # ) -> Tuple[List[PartnerSchema], int]: # 반환 타입을 Schema로 변경
    #     """파트너 목록 조회 (필터링 및 정렬 포함) - BaseService 오버라이드 예시"""
    #     entities, total = await self.partner_repo.list_partners(skip=skip, limit=limit, filters=filters, sort_by=sort_by, sort_order=sort_order)
    #     return [self._entity_to_schema(entity) for entity in entities], total

    # create 메소드는 BaseService 것을 사용 -> _create_entity 구현 필요
    # async def create(self, partner_data: PartnerCreate) -> PartnerSchema: # 반환 타입을 Schema로 변경
    #     """새 파트너 생성 - BaseService 오버라이드"""
    #     # BaseService의 _validate_create_data 후크 사용 또는 직접 검사
    #     await self._validate_create_data(partner_data)
    #     
    #     partner_dict = partner_data.model_dump()
    #     new_partner = self.model_class(**partner_dict)
    #     
    #     try:
    #         created_partner = await self.partner_repo.create_partner(new_partner)
    #         logger.info(f"Created new {self.entity_name}: {created_partner.code} ({getattr(created_partner, self.id_field)}) ")
    #         return self._entity_to_schema(created_partner)
    #     except Exception as e:
    #         logger.error(f"Database error creating {self.entity_name} {partner_data.code}: {e}", exc_info=True)
    #         raise DatabaseError(f"Failed to create {self.entity_name} due to database error.") from e

    # update 메소드는 BaseService 것을 사용 -> _update_entity 구현 필요
    # async def update(self, partner_id: UUID, partner_update: PartnerUpdate) -> PartnerSchema: # 반환 타입을 Schema로 변경
    #     """파트너 정보 업데이트 - BaseService 오버라이드"""
    #     partner_to_update = await self.get_or_404(partner_id) # BaseService의 get_or_404 사용
    #     
    #     # BaseService의 _validate_update_data 후크 사용 또는 직접 검사
    #     await self._validate_update_data(partner_to_update, partner_update)
    # 
    #     update_data = partner_update.model_dump(exclude_unset=True)
    #     
    #     # Prevent updating code? Or allow if admin? (This logic remains here)
    #     if 'code' in update_data:
    #          logger.warning(f"Attempt to update partner code for {partner_id} - disallowed.")
    #          del update_data['code'] # Example: disallow code update
    #          
    #     try:
    #         updated_partner = await self.partner_repo.update_partner(partner_to_update, update_data)
    #         logger.info(f"Updated {self.entity_name}: {updated_partner.code} ({getattr(updated_partner, self.id_field)}) ")
    #         # await self.invalidate_partner_cache(partner_id) # Invalidate cache if caching is enabled
    #         return self._entity_to_schema(updated_partner)
    #     except Exception as e:
    #         logger.error(f"Database error updating {self.entity_name} {partner_id}: {e}", exc_info=True)
    #         raise DatabaseError(f"Failed to update {self.entity_name} due to database error.") from e
            
    # delete 메소드는 BaseService 것을 사용 -> _delete_entity 구현 필요
    # async def delete(self, partner_id: UUID) -> bool:
    #     """파트너 삭제 (논리적 삭제) - BaseService 오버라이드"""
    #     partner_to_delete = await self.get_or_404(partner_id)
    #     
    #     try:
    #         # Soft delete logic
    #         success = await self.partner_repo.update_partner(partner_to_delete, {"status": PartnerStatus.TERMINATED, "is_active": False})
    #         
    #         if success:
    #             logger.info(f"{self.entity_name} {partner_id} marked as terminated (soft deleted).")
    #             # await self.invalidate_partner_cache(partner_id) # Invalidate cache
    #             return True
    #         else:
    #             logger.error(f"Failed to soft-delete {self.entity_name} {partner_id} in repository.")
    #             return False # Or raise an error
    #     except Exception as e:
    #         logger.error(f"Database error deleting/terminating {self.entity_name} {partner_id}: {e}", exc_info=True)
    #         raise DatabaseError(f"Failed to delete/terminate {self.entity_name} due to database error.") from e
            
    # --- BaseService 추상 메소드 구현 --- 
    
    async def _find_one(self, query: Dict[str, Any]) -> Optional[PartnerModel]:
        """주어진 쿼리로 파트너 조회 (레포지토리 사용)"""
        # BaseService의 get_or_404는 {id_field: value} 형태의 query를 전달
        if len(query) == 1 and self.id_field in query:
            return await self.partner_repo.get_partner_by_id(query[self.id_field])
        elif len(query) == 1 and 'code' in query: # 다른 조회 조건 예시 (예: validate_create_data에서 사용)
            return await self.partner_repo.get_partner_by_code(query['code'])
        
        # BaseService의 기본 동작(ID 조회) 외의 쿼리는 여기서 직접 처리하거나 에러 발생
        # logger.warning(f"_find_one called with unhandled query: {query} in PartnerService")
        # raise NotImplementedError(f"Query not supported by _find_one: {query}")
        return None # 기본적으로 ID 조회만 지원

    async def _find_many(self, skip: int, limit: int, 
                         filters: Optional[Dict[str, Any]], 
                         sort_by: Optional[str], sort_order: str
    ) -> Tuple[List[PartnerModel], int]:
        """파트너 목록 조회 (레포지토리 사용)"""
        return await self.partner_repo.list_partners(
            skip=skip, limit=limit, filters=filters, sort_by=sort_by, sort_order=sort_order
        )

    async def _create_entity(self, data: Dict[str, Any]) -> PartnerModel:
        """새 파트너 생성 (레포지토리 사용)"""
        # Validation (_validate_create_data)은 BaseService.create에서 이미 호출됨
        new_partner = self.model_class(**data)
        return await self.partner_repo.create_partner(new_partner)

    async def _update_entity(self, entity: PartnerModel, data: Dict[str, Any]) -> PartnerModel:
        """파트너 정보 업데이트 (레포지토리 사용, 코드 업데이트 방지 로직 포함)"""
        # Validation (_validate_update_data)은 BaseService.update에서 이미 호출됨
        
        # Prevent updating partner code
        if 'code' in data:
            logger.warning(f"Attempt to update partner code for {entity.id} - disallowed.")
            del data['code']
            
        if not data: # If only 'code' was provided and removed, there's nothing to update
             logger.info(f"Update request for partner {entity.id} contained only 'code', no changes applied.")
             return entity # Return the original entity without hitting the repo

        return await self.partner_repo.update_partner(entity, data)

    async def _delete_entity(self, entity: PartnerModel) -> bool:
        """파트너 삭제 (논리적 삭제, 레포지토리 사용)"""
        # BaseService.delete에서 get_or_404는 이미 호출됨
        update_data = {"status": PartnerStatus.TERMINATED, "is_active": False}
        updated_partner = await self.partner_repo.update_partner(entity, update_data)
        # Return True if update was seemingly successful (repo didn't raise error)
        # Note: updated_partner might return the updated entity or a boolean. Adjust accordingly.
        # Assuming updated_partner returns the updated entity on success:
        return updated_partner is not None
        
    # --- Validation Hooks 오버라이드 (유지) --- 
    
    async def _validate_create_data(self, data: PartnerCreate) -> None:
        """파트너 생성 데이터 유효성 검사 (코드 중복 확인)"""
        existing_code = await self.partner_repo.get_partner_by_code(data.code)
        if existing_code:
            logger.warning(f"Attempt to create partner with duplicate code: {data.code}")
            raise ConflictError(f"Partner code '{data.code}' already exists.")
            
        # Add email check if necessary
        # existing_email = await self.partner_repo.get_partner_by_email(data.contact_email)
        # if existing_email:
        #     raise ConflictError(f"Partner contact email '{data.contact_email}' already exists.")

    async def _validate_update_data(self, entity: PartnerModel, data: PartnerUpdate) -> None:
        """파트너 업데이트 데이터 유효성 검사 (필요시 이름 충돌 등 확인)"""
        # Example: Check name conflict if name is being updated
        # update_dict = data.model_dump(exclude_unset=True)
        # if 'name' in update_dict and update_dict['name'] != entity.name:
        #     existing = await self.partner_repo.get_partner_by_name(update_dict['name'])
        #     if existing and existing.id != entity.id:
        #         raise ConflictError(f"Partner name '{update_dict['name']}' already exists.")
        pass # No extra validation for now

    # --- Partner 특화 기능들 (기존 코드 유지) --- 

    async def create_api_key(self, partner_id: UUID, api_key_data: ApiKeyCreate) -> Tuple[ApiKeyModel, str]:
        """새 API 키 생성 및 비밀 키 반환"""
        partner = await self.get_or_404(partner_id) # Use BaseService method
        
        key_prefix = f"bk_{partner.code[:4]}_"
        api_key_str = key_prefix + secrets.token_urlsafe(32)
        secret, hashed_secret = generate_api_secret()
        
        key_dict = api_key_data.model_dump()
        key_dict.update({
            "partner_id": partner_id,
            "key": api_key_str,
            "hashed_secret": hashed_secret,
            "is_active": True
        })
        
        new_api_key = ApiKeyModel(**key_dict)
        
        try:
            created_key = await self.partner_repo.create_api_key(new_api_key)
            logger.info(f"Created new API key {created_key.id} for partner {partner_id}")
            return created_key, secret # Return model instance and plain secret
        except Exception as e:
            logger.error(f"Database error creating API key for partner {partner_id}: {e}", exc_info=True)
            raise APIKeyGenerationError("Failed to save new API key.") from e

    async def list_api_keys(self, partner_id: UUID) -> List[ApiKeyModel]:
        """파트너의 활성 API 키 목록 조회"""
        await self.get_or_404(partner_id) # Ensure partner exists
        return await self.partner_repo.get_api_keys_by_partner(partner_id)

    async def deactivate_api_key(self, partner_id: UUID, key_id: UUID) -> bool:
        """API 키 비활성화 (권한 확인은 API 레이어)"""
        api_key = await self.partner_repo.get_api_key_by_id(key_id)
        if not api_key or api_key.partner_id != partner_id:
             logger.warning(f"API key {key_id} not found or does not belong to partner {partner_id}")
             raise NotFoundError(f"API key with ID {key_id} not found for this partner.")
             
        if not api_key.is_active:
            logger.info(f"API key {key_id} is already inactive.")
            return True # Already inactive
            
        try:
            success = await self.partner_repo.update_api_key(api_key, {"is_active": False})
            if success:
                logger.info(f"Deactivated API key {key_id} for partner {partner_id}")
                return True
            else:
                 logger.error(f"Failed to deactivate API key {key_id} in repository.")
                 return False
        except Exception as e:
            logger.error(f"Database error deactivating API key {key_id}: {e}", exc_info=True)
            raise DatabaseError("Failed to deactivate API key.") from e
            
    async def validate_api_key(self, key_str: str, secret_str: str) -> Optional[PartnerSchema]:
        """API 키와 시크릿 검증 후 활성 파트너 반환"""
        api_key = await self.partner_repo.get_api_key_by_key(key_str)
        
        if not api_key or not api_key.is_active:
            logger.debug(f"API key validation failed: Key not found or inactive ({key_str[:10]}...)")
            return None # Key not found or inactive
            
        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            logger.warning(f"API key validation failed: Key expired ({key_str[:10]}...)")
            # Optionally deactivate the key here
            # await self.deactivate_api_key(api_key.partner_id, api_key.id)
            return None # Key expired
            
        if not verify_password(secret_str, api_key.hashed_secret):
            logger.warning(f"API key validation failed: Invalid secret ({key_str[:10]}...)")
            return None # Invalid secret
        
        # Key and secret are valid, fetch the partner
        partner = await self.partner_repo.get_partner_by_id(api_key.partner_id)
        
        if not partner or partner.status != PartnerStatus.ACTIVE:
             logger.warning(f"API key validation failed: Partner not found or inactive (Partner ID: {api_key.partner_id}, Key: {key_str[:10]}...)")
             return None # Partner not found or not active
             
        # Update last used time (optional, consider performance impact)
        # await self.partner_repo.update_api_key(api_key, {"last_used_at": datetime.utcnow()})
        
        logger.debug(f"API key validated successfully for partner {partner.id} ({key_str[:10]}...)")
        return self._entity_to_schema(partner)

    # --- Partner Settings Management --- 

    async def update_or_create_partner_setting(self, partner_id: UUID, setting_data: PartnerSettingCreate) -> Tuple[PartnerSettingModel, bool]:
        """파트너 설정 생성 또는 업데이트"""
        await self.get_or_404(partner_id) # Ensure partner exists
        
        setting_key = setting_data.setting_key # Use the alias if defined in schema
        
        existing_setting = await self.partner_repo.get_partner_setting(partner_id, setting_key)
        
        setting_dict = setting_data.model_dump()
        created = False
        
        try:
            if existing_setting:
                # Update existing setting
                updated_setting = await self.partner_repo.update_partner_setting(existing_setting, setting_dict)
                logger.info(f"Updated setting '{setting_key}' for partner {partner_id}")
                result_setting = updated_setting
            else:
                # Create new setting
                setting_dict['partner_id'] = partner_id
                new_setting = PartnerSettingModel(**setting_dict)
                created_setting = await self.partner_repo.create_partner_setting(new_setting)
                logger.info(f"Created setting '{setting_key}' for partner {partner_id}")
                result_setting = created_setting
                created = True
                
            return result_setting, created
        except Exception as e:
            logger.error(f"Database error managing setting '{setting_key}' for partner {partner_id}: {e}", exc_info=True)
            raise DatabaseError("Failed to manage partner setting.") from e
            
    async def list_partner_settings(self, partner_id: UUID) -> List[PartnerSettingModel]:
        """특정 파트너의 모든 설정 조회"""
        await self.get_or_404(partner_id) # Ensure partner exists
        return await self.partner_repo.get_partner_settings_by_partner(partner_id)
        
    async def get_partner_setting_value(self, partner_id: UUID, key: str, default: Optional[Any] = None) -> Optional[Any]:
        """특정 파트너 설정 값 조회 (타입 변환 포함)"""
        setting = await self.partner_repo.get_partner_setting(partner_id, key)
        if not setting:
            return default
            
        # Convert value based on value_type
        try:
            if setting.value_type == 'int': return int(setting.setting_value)
            if setting.value_type == 'float': return float(setting.setting_value)
            if setting.value_type == 'bool': return setting.setting_value.lower() in ['true', '1', 'yes']
            # Add json or other types if needed
            return setting.setting_value # Default to string
        except ValueError as e:
             logger.error(f"Failed to convert setting '{key}' value '{setting.setting_value}' to type '{setting.value_type}' for partner {partner_id}: {e}")
             return default # Return default if conversion fails

    # --- Partner IP Whitelist Management --- 

    async def add_partner_ip(self, partner_id: UUID, ip_data: PartnerIPCreate) -> PartnerIPModel:
        """파트너 IP 화이트리스트에 추가"""
        await self.get_or_404(partner_id) # Ensure partner exists
        
        # TODO: Add validation for ip_data.ip_address format (IPv4, IPv6, CIDR)
        # try:
        #     validate_ip_address(ip_data.ip_address) # Assumes a validation utility
        # except ValueError as e:
        #     raise InvalidInputError(f"Invalid IP address format: {e}")
            
        existing_ip = await self.partner_repo.get_partner_ip_by_address(partner_id, ip_data.ip_address)
        if existing_ip:
            raise ConflictError(f"IP address '{ip_data.ip_address}' already exists in the whitelist for this partner.")
            
        ip_dict = ip_data.model_dump()
        ip_dict['partner_id'] = partner_id
        ip_dict['is_active'] = True # Default to active
        new_ip = PartnerIPModel(**ip_dict)
        
        try:
            created_ip = await self.partner_repo.create_partner_ip(new_ip)
            logger.info(f"Added IP {created_ip.ip_address} to whitelist for partner {partner_id}")
            return created_ip
        except Exception as e:
            logger.error(f"Database error adding IP {ip_data.ip_address} for partner {partner_id}: {e}", exc_info=True)
            raise DatabaseError("Failed to add IP address.") from e

    async def remove_partner_ip(self, partner_id: UUID, ip_id: UUID) -> bool:
        """파트너 IP 화이트리스트에서 제거 (ID 기준, 권한 확인은 API 레이어)"""
        ip_entry = await self.partner_repo.get_partner_ip_by_id(ip_id)
        
        if not ip_entry or ip_entry.partner_id != partner_id:
            logger.warning(f"IP entry {ip_id} not found or does not belong to partner {partner_id}")
            raise NotFoundError(f"IP whitelist entry with ID {ip_id} not found for this partner.")
            
        try:
            # Option 1: Soft delete
            # success = await self.partner_repo.update_partner_ip(ip_entry, {"is_active": False})
            # Option 2: Hard delete
            success = await self.partner_repo.delete_partner_ip(ip_entry)
            
            if success:
                logger.info(f"Removed IP entry {ip_id} ({ip_entry.ip_address}) from whitelist for partner {partner_id}")
                return True
            else:
                logger.error(f"Failed to remove IP entry {ip_id} in repository.")
                return False
        except Exception as e:
            logger.error(f"Database error removing IP entry {ip_id} for partner {partner_id}: {e}", exc_info=True)
            raise DatabaseError("Failed to remove IP address.") from e

    async def list_partner_ips(self, partner_id: UUID) -> List[PartnerIPModel]:
        """파트너의 활성 IP 화이트리스트 조회"""
        await self.get_or_404(partner_id) # Ensure partner exists
        return await self.partner_repo.get_partner_ips_by_partner(partner_id)

    # async def check_ip_allowed(self, partner_id: UUID, ip_address: str) -> bool:
    #     """주어진 IP가 파트너 화이트리스트에 있는지 확인 (CIDR 포함)"""
    #     allowed_ips = await self.list_partner_ips(partner_id)
    #     # TODO: Implement CIDR matching logic if needed
    #     return any(entry.ip_address == ip_address for entry in allowed_ips if entry.is_active) 