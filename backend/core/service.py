from typing import Generic, TypeVar, Type, List, Optional, Dict, Any, Tuple, Union
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from uuid import UUID, uuid4
from datetime import datetime # Import datetime for timing
from sqlalchemy.orm import Session

from backend.core.exceptions import NotFoundError, ValidationError, DatabaseError
from backend.core.logging import StructuredLogger

T = TypeVar('T')  # 데이터베이스 모델
S = TypeVar('S')  # 응답 스키마
C = TypeVar('C')  # 생성 스키마
U = TypeVar('U')  # 업데이트 스키마

class BaseService(Generic[T, S, C, U]):
    """모든 CRUD 서비스의 기본 클래스"""
    
    # These should be overridden by subclasses
    service_name: str = "base"
    entity_name: str = "record"
    id_field: str = "id"
    not_found_exception_class: Type[Exception] = NotFoundError
    
    def __init__(
        self, 
        db: AsyncSession,
        model_class: Type[T],
        response_schema_class: Type[S],
        create_schema_class: Optional[Type[C]] = None, # Made optional
        update_schema_class: Optional[Type[U]] = None, # Made optional
    ):
        self.db = db
        self.model_class = model_class
        self.response_schema_class = response_schema_class
        # Default create/update schemas to response schema if not provided
        self.create_schema_class = create_schema_class or response_schema_class 
        self.update_schema_class = update_schema_class or self.create_schema_class
        
        # Initialize StructuredLogger
        self.logger = StructuredLogger(f"service.{self.service_name}")
        
        # Pass context info directly to logger
        self.logger.debug(f"Initialized {self.service_name} service", 
                          service_name=self.service_name, 
                          entity_name=self.entity_name)
    
    async def get(self, id_value: Union[str, int, UUID]) -> S:
        """ID로 항목 조회"""
        self.logger.debug(
            f"Getting {self.entity_name} by ID", 
            operation="get", 
            entity_id=str(id_value) # Ensure ID is string for logging
        )
        try:
            entity = await self.get_or_404(id_value)
            return self._entity_to_schema(entity)
        except Exception as e:
            self.logger.error(
                f"Error getting {self.entity_name}", 
                operation="get", 
                entity_id=str(id_value),
                exception=e
            )
            raise # Re-raise the original exception to be handled by global handlers
    
    async def list(self, skip: int = 0, limit: int = 100, 
                  filters: Optional[Dict[str, Any]] = None,
                  sort_by: Optional[str] = None, 
                  sort_order: str = "asc") -> Tuple[List[S], int]:
        """목록 조회"""
        start_time = datetime.utcnow()
        self.logger.debug(
            f"Listing {self.entity_name}s", 
            operation="list", 
            context={"skip": skip, "limit": limit, "filters": filters, "sort_by": sort_by, "sort_order": sort_order}
        )
        try:
            entities, total = await self._find_many(
                skip=skip, limit=limit, filters=filters,
                sort_by=sort_by, sort_order=sort_order
            )
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            self.logger.info(
                f"Found {len(entities)} {self.entity_name}(s) out of {total}", 
                operation="list", 
                duration_ms=elapsed, # Log performance
                context={"count": len(entities), "total": total}
            )
            return [self._entity_to_schema(entity) for entity in entities], total
        except Exception as e:
            self.logger.error(
                f"Error listing {self.entity_name}s", 
                operation="list", 
                exception=e,
                context={"skip": skip, "limit": limit, "filters": filters, "sort_by": sort_by, "sort_order": sort_order}
            )
            raise
    
    async def create(self, data: C) -> S:
        """새 항목 생성"""
        start_time = datetime.utcnow()
        # Context data will be sanitized by the logger
        self.logger.info(
            f"Attempting to create new {self.entity_name}", 
            operation="create", 
            context={"data": data.model_dump(exclude_unset=True)}
        )
        
        try:
            await self._validate_create_data(data)
            entity_data = data.model_dump()
            created_entity = await self._create_entity(entity_data)
            entity_id = getattr(created_entity, self.id_field, 'N/A')
            await self.db.commit()
            await self.db.refresh(created_entity)
            result = self._entity_to_schema(created_entity)
            
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            self.logger.info(
                f"Successfully created {self.entity_name}", 
                operation="create", 
                entity_id=str(entity_id), 
                duration_ms=elapsed # Log performance
            )
            return result
        except Exception as e:
            await self.db.rollback()
            self.logger.error(
                f"Failed to create {self.entity_name}", 
                operation="create", 
                exception=e, 
                context={"data": data.model_dump(exclude_unset=True)} # Log original input on error
            )
            # Wrap specific DB errors if necessary, otherwise let global handler manage
            if "database error" in str(e).lower(): # Basic check, improve if needed
                 raise DatabaseError(f"Failed to create {self.entity_name} due to database error.") from e
            raise # Re-raise other exceptions
            
    async def update(self, id_value: Union[str, int, UUID], data: U) -> S:
        """항목 업데이트"""
        start_time = datetime.utcnow()
        # Context data will be sanitized by the logger
        self.logger.info(
            f"Attempting to update {self.entity_name}", 
            operation="update", 
            entity_id=str(id_value),
            context={"data": data.model_dump(exclude_unset=True)}
        )
        
        try:
            entity_to_update = await self.get_or_404(id_value)
            await self._validate_update_data(entity_to_update, data)
            update_data = data.model_dump(exclude_unset=True)
            updated_entity = await self._update_entity(entity_to_update, update_data)
            await self.db.commit()
            await self.db.refresh(updated_entity)
            result = self._entity_to_schema(updated_entity)
            
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            self.logger.info(
                f"Successfully updated {self.entity_name}", 
                operation="update", 
                entity_id=str(id_value), 
                duration_ms=elapsed # Log performance
            )
            return result
        except Exception as e:
            await self.db.rollback()
            self.logger.error(
                f"Failed to update {self.entity_name}", 
                operation="update", 
                entity_id=str(id_value), 
                exception=e, 
                context={"data": data.model_dump(exclude_unset=True)}
            )
            if "database error" in str(e).lower():
                 raise DatabaseError(f"Failed to update {self.entity_name} due to database error.") from e
            raise

    async def delete(self, id_value: Union[str, int, UUID]) -> bool:
        """항목 삭제"""
        start_time = datetime.utcnow()
        self.logger.info(
            f"Attempting to delete {self.entity_name}", 
            operation="delete", 
            entity_id=str(id_value)
        )
        
        try:
            entity_to_delete = await self.get_or_404(id_value)
            success = await self._delete_entity(entity_to_delete)
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            if success:
                await self.db.commit()
                self.logger.info(
                    f"Successfully deleted {self.entity_name}", 
                    operation="delete", 
                    entity_id=str(id_value), 
                    duration_ms=elapsed # Log performance
                )
            else:
                await self.db.rollback()
                self.logger.warning(
                    f"Deletion of {self.entity_name} indicated as failed by _delete_entity", 
                    operation="delete", 
                    entity_id=str(id_value),
                    duration_ms=elapsed
                )
            return success
        except Exception as e:
            await self.db.rollback()
            self.logger.error(
                f"Failed to delete {self.entity_name}", 
                operation="delete", 
                entity_id=str(id_value), 
                exception=e
            )
            if "database error" in str(e).lower():
                 raise DatabaseError(f"Failed to delete {self.entity_name} due to database error.") from e
            raise

    async def get_or_404(self, id_value: Union[str, int, UUID]) -> T:
        """ID로 항목 조회하거나 지정된 NotFound 예외 발생"""
        # Logging is done within self.get and _find_one or by the caller
        # Keep the warning log for the specific case where the entity is not found
        query = {self.id_field: id_value}
        entity = await self._find_one(query)
        
        if not entity:
            self.logger.warning(
                f"{self.entity_name.capitalize()} not found", 
                operation="get_or_404", 
                entity_id=str(id_value), 
                field=self.id_field
            )
            raise self.not_found_exception_class(
                f"{self.entity_name.capitalize()} with {self.id_field}={id_value} not found"
            )
        # Debug log for successful find can be added here if needed, or rely on _find_one log
        return entity
    
    # --- Helper / Internal Methods --- 

    def _entity_to_schema(self, entity: T) -> S:
        """DB 모델 엔티티를 응답 스키마로 변환"""
        # This assumes the response schema can be directly initialized from the model
        # May need adjustments based on actual schema/model structures
        return self.response_schema_class.model_validate(entity) # Use Pydantic v2 method

    # --- Methods for Subclass Override/Implementation --- 

    async def _validate_create_data(self, data: C) -> None:
        """생성 데이터 유효성 검사 (필요시 서브클래스에서 오버라이드)"""
        # Example: Check for conflicts, business rules etc.
        pass
    
    async def _validate_update_data(self, entity: T, data: U) -> None:
        """업데이트 데이터 유효성 검사 (필요시 서브클래스에서 오버라이드)"""
        # Example: Check for state transitions, business rules etc.
        pass
    
    # --- Abstract Database Interaction Methods (MUST be implemented by subclasses) ---

    async def _find_one(self, query: Dict[str, Any]) -> Optional[T]:
        """주어진 쿼리로 단일 엔티티 조회 (서브클래스에서 레포지토리/DB 직접 호출)"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement _find_one")
        
    async def _find_many(self, skip: int, limit: int, 
                         filters: Optional[Dict[str, Any]], 
                         sort_by: Optional[str], sort_order: str) -> Tuple[List[T], int]:
        """다중 엔티티 조회 (필터링, 정렬, 페이지네이션 포함) (서브클래스에서 레포지토리/DB 직접 호출)"""
        raise NotImplementedError(f"{self.__class__.__name__} must implement _find_many")
    
    async def _create_entity(self, data: Dict[str, Any]) -> T:
        """주어진 데이터로 새 엔티티를 DB에 생성 (서브클래스에서 레포지토리/DB 직접 호출)"""
        # Example implementation might look like:
        # new_entity = self.model_class(**data)
        # self.db.add(new_entity)
        # await self.db.flush() # Flush to get potential DB-generated IDs before returning
        # return new_entity
        raise NotImplementedError(f"{self.__class__.__name__} must implement _create_entity")
    
    async def _update_entity(self, entity: T, data: Dict[str, Any]) -> T:
        """기존 엔티티를 주어진 데이터로 DB에서 업데이트 (서브클래스에서 레포지토리/DB 직접 호출)"""
        # Example implementation might look like:
        # for key, value in data.items():
        #     setattr(entity, key, value)
        # self.db.add(entity) # Add to session to track changes
        # await self.db.flush() # Flush to apply changes
        # return entity
        raise NotImplementedError(f"{self.__class__.__name__} must implement _update_entity")
    
    async def _delete_entity(self, entity: T) -> bool:
        """주어진 엔티티를 DB에서 삭제 (논리적/물리적 삭제는 구현에 따름) (서브클래스에서 레포지토리/DB 직접 호출)"""
        # Example physical delete:
        # await self.db.delete(entity)
        # await self.db.flush()
        # return True
        # Example logical delete:
        # setattr(entity, 'is_active', False)
        # setattr(entity, 'deleted_at', datetime.utcnow())
        # self.db.add(entity)
        # await self.db.flush()
        # return True
        raise NotImplementedError(f"{self.__class__.__name__} must implement _delete_entity")
    
    # Add other common helper or abstract methods as needed
    # e.g., _check_conflict, _apply_filters, etc. 