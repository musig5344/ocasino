from typing import Generic, TypeVar, Type, List, Dict, Any, Optional, Tuple, Union
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, asc, desc
from sqlalchemy.orm import joinedload, selectinload # Use selectinload for async relationships
from sqlalchemy.sql.elements import BinaryExpression # For type hinting filter expressions
from sqlalchemy.exc import NoResultFound # For potential error handling
import logging

T = TypeVar('T')  # 데이터베이스 모델 타입

logger = logging.getLogger(__name__)

class BaseRepository(Generic[T]):
    """
    모든 레포지토리의 기본 클래스.
    데이터베이스 액세스를 캡슐화하고 표준화합니다.
    """

    def __init__(self, db: AsyncSession, model_class: Type[T]):
        """
        Parameters:
            db: SQLAlchemy 비동기 세션
            model_class: 이 레포지토리가 다루는 모델 클래스
        """
        if not db:
            raise ValueError("Database session is required for BaseRepository.")
        if not model_class:
             raise ValueError("Model class is required for BaseRepository.")
             
        self.db = db
        self.model_class = model_class
        # Default ID field, can be overridden by subclasses if needed
        self.id_field_name = "id" 

    def _apply_filters(self, query, filters: Optional[Dict[str, Any]] = None):
        """
        쿼리에 필터 조건 적용. 
        Supports basic equality and operators like 'in', 'notin', 'lt', 'lte', 'gt', 'gte', 'icontains'.
        Example: filters = {"status": "active", "amount__gt": 100, "name__icontains": "test"}
        """
        if not filters:
            return query

        for key, value in filters.items():
            if value is None: # Skip None values unless specifically handled
                continue

            field_name = key
            operator = None

            if "__" in key:
                parts = key.split("__", 1)
                field_name = parts[0]
                operator = parts[1].lower()

            # Ensure the field exists on the model
            if not hasattr(self.model_class, field_name):
                logger.warning(f"Filtering skipped: Field '{field_name}' not found on model {self.model_class.__name__}.")
                continue

            column = getattr(self.model_class, field_name)

            if operator == "in":
                if isinstance(value, list) and len(value) > 0:
                    query = query.where(column.in_(value))
                elif not isinstance(value, list):
                     logger.warning(f"Filter '{key}': 'in' operator requires a non-empty list, got {type(value)}.")
                # Ignore empty lists for 'in'
            elif operator == "notin":
                 if isinstance(value, list) and len(value) > 0:
                     query = query.where(column.notin_(value))
                 elif not isinstance(value, list):
                     logger.warning(f"Filter '{key}': 'notin' operator requires a non-empty list, got {type(value)}.")
                 # Ignore empty lists for 'notin'
            elif operator == "lt":
                query = query.where(column < value)
            elif operator == "lte":
                query = query.where(column <= value)
            elif operator == "gt":
                query = query.where(column > value)
            elif operator == "gte":
                query = query.where(column >= value)
            elif operator == "icontains": # Case-insensitive contains
                query = query.where(column.ilike(f"%{value}%"))
            elif operator == "isnull": # Check for null
                 if isinstance(value, bool):
                     query = query.where(column == None) if value else query.where(column != None) # noqa: E711
                 else:
                      logger.warning(f"Filter '{key}': 'isnull' operator requires a boolean value.")
            elif operator is None: # Default to equality
                query = query.where(column == value)
            else:
                logger.warning(f"Unsupported filter operator '{operator}' for key '{key}'. Skipping.")
                
        return query

    async def find_one(self, filters: Dict[str, Any], load_relations: Optional[List[str]] = None) -> Optional[T]:
        """
        필터 조건에 맞는 단일 항목 조회
        
        Parameters:
            filters: 필터 조건 딕셔너리 (예: {"id": uuid, "status": "active"})
            load_relations: 함께 로드할 관계 필드 목록 (문자열)
            
        Returns:
            조건에 맞는 항목 또는 None
        """
        if not filters:
            logger.warning("find_one called without filters. This might return an arbitrary record.")
            # Consider raising an error or requiring filters for find_one
            # raise ValueError("Filters are required for find_one operation.")

        query = select(self.model_class)

        # 관계 필드 로드 설정 (use selectinload for async)
        if load_relations:
            for relation_name in load_relations:
                if hasattr(self.model_class, relation_name):
                    query = query.options(selectinload(getattr(self.model_class, relation_name)))
                else:
                     logger.warning(f"Relation '{relation_name}' not found on model {self.model_class.__name__} for eager loading.")

        # 필터 적용
        query = self._apply_filters(query, filters)

        # Execute query
        try:
            result = await self.db.execute(query)
            return result.scalars().first()
        except Exception as e:
            logger.error(f"Error executing find_one query: {e}", exc_info=True)
            # Depending on policy, you might re-raise or return None
            # raise DatabaseError("Failed to execute find_one query.") from e
            return None

    async def find_many(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None,
        sort_by: Optional[str] = None,
        sort_order: str = "asc",
        load_relations: Optional[List[str]] = None
    ) -> List[T]:
        """
        필터링, 정렬, 페이지네이션을 지원하는 다중 항목 조회
        
        Parameters:
            skip: 건너뛸 항목 수 (0 이상)
            limit: 반환할 최대 항목 수 (0이면 제한 없음 - 주의해서 사용)
            filters: 필터 조건 딕셔너리
            sort_by: 정렬 기준 필드 이름
            sort_order: 정렬 방향 ("asc" 또는 "desc")
            load_relations: 함께 로드할 관계 필드 목록 (문자열)
            
        Returns:
            조건에 맞는 항목 목록
        """
        if skip < 0:
            raise ValueError("Skip must be non-negative.")
        # Limit 0 can be dangerous, often better to enforce a max limit
        if limit < 0:
             raise ValueError("Limit must be non-negative.")
             
        query = select(self.model_class)

        # 관계 필드 로드 설정
        if load_relations:
            for relation_name in load_relations:
                 if hasattr(self.model_class, relation_name):
                     query = query.options(selectinload(getattr(self.model_class, relation_name)))
                 else:
                     logger.warning(f"Relation '{relation_name}' not found on model {self.model_class.__name__} for eager loading.")

        # 필터 적용
        query = self._apply_filters(query, filters)

        # 정렬 적용
        if sort_by:
            if not hasattr(self.model_class, sort_by):
                logger.warning(f"Sorting skipped: Sort field '{sort_by}' not found on model {self.model_class.__name__}.")
            else:
                column = getattr(self.model_class, sort_by)
                if sort_order.lower() == "desc":
                    query = query.order_by(desc(column))
                else:
                    query = query.order_by(asc(column))
        # else: Add default sorting if needed, e.g., by primary key or created_at
        #    default_sort_field = getattr(self.model_class, self.id_field_name, None) or getattr(self.model_class, 'created_at', None)
        #    if default_sort_field:
        #         query = query.order_by(asc(default_sort_field))


        # 페이지네이션 적용
        if skip > 0:
            query = query.offset(skip)
        if limit > 0: # Apply limit only if it's positive
            query = query.limit(limit)

        # Execute query
        try:
            result = await self.db.execute(query)
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error executing find_many query: {e}", exc_info=True)
            # raise DatabaseError("Failed to execute find_many query.") from e
            return [] # Return empty list on error? Or re-raise?

    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """필터 조건에 맞는 항목 개수 조회"""
        # Construct the count query, applying the same filters
        query = select(func.count(getattr(self.model_class, self.id_field_name, self.model_class.__mapper__.primary_key[0]))).select_from(self.model_class)
        
        # 필터 적용
        query = self._apply_filters(query, filters)

        # Execute query
        try:
            result = await self.db.execute(query)
            count = result.scalar_one_or_none()
            return count or 0
        except Exception as e:
            logger.error(f"Error executing count query: {e}", exc_info=True)
            # raise DatabaseError("Failed to execute count query.") from e
            return 0 # Return 0 on error?
            
    # --- Create, Update, Delete methods --- 

    async def create(self, data: Dict[str, Any]) -> T:
        """새 항목 생성"""
        try:
            # Create model instance
            new_item = self.model_class(**data)
            # Add to session
            self.db.add(new_item)
            # Flush to send the insert to the DB and get potential defaults/IDs
            await self.db.flush()
            # Refresh the instance to get the latest state from the DB
            await self.db.refresh(new_item)
            logger.debug(f"Created {self.model_class.__name__} record with ID: {getattr(new_item, self.id_field_name, 'N/A')}")
            return new_item
        except Exception as e:
            # Rollback is typically handled by the service layer or context manager
            logger.error(f"Error creating {self.model_class.__name__} record: {e}", exc_info=True)
            # Re-raise the exception to be handled by the caller (service)
            raise

    async def update(self, item_id: Union[UUID, str, int], data: Dict[str, Any]) -> Optional[T]:
        """ID로 항목을 찾아 주어진 데이터로 업데이트합니다."""
        try:
            # Find the item first
            item_to_update = await self.find_one(filters={self.id_field_name: item_id})
            
            if not item_to_update:
                logger.warning(f"Update failed: {self.model_class.__name__} with {self.id_field_name}={item_id} not found.")
                return None # Or raise NotFoundError if preferred by design

            # Update attributes
            for key, value in data.items():
                if hasattr(item_to_update, key):
                    setattr(item_to_update, key, value)
                else:
                    logger.warning(f"Update skipped for field '{key}': Not found on model {self.model_class.__name__}.")
            
            # Add to session (SQLAlchemy tracks changes on attached objects)
            # self.db.add(item_to_update) # Usually not needed if object is already in session
            
            # Flush changes to the DB
            await self.db.flush()
            # Refresh to get the updated state
            await self.db.refresh(item_to_update)
            logger.debug(f"Updated {self.model_class.__name__} record with ID: {item_id}")
            return item_to_update
            
        except Exception as e:
            logger.error(f"Error updating {self.model_class.__name__} record with ID {item_id}: {e}", exc_info=True)
            raise

    async def delete(self, item_id: Union[UUID, str, int], soft_delete: bool = False) -> bool:
        """
        항목 삭제 (soft_delete=True 시 상태 변경, False 시 실제 삭제)
        
        Soft delete requires the model to have an 'is_active' (boolean) or 'status' field.
        Modify field names ('is_active', 'status', 'DELETED_STATUS') as per your models.
        """
        try:
            # Find the item first
            item_to_delete = await self.find_one(filters={self.id_field_name: item_id})

            if not item_to_delete:
                logger.warning(f"Delete failed: {self.model_class.__name__} with {self.id_field_name}={item_id} not found.")
                return False

            if soft_delete:
                # Attempt soft delete by setting standard fields
                updated = False
                soft_delete_fields = {"is_active": False, "status": "deleted"} # Common fields
                
                for field, value in soft_delete_fields.items():
                     if hasattr(item_to_delete, field):
                         # Check current value to avoid unnecessary updates? Optional.
                         # if getattr(item_to_delete, field) != value:
                         setattr(item_to_delete, field, value)
                         updated = True
                         logger.debug(f"Soft deleting {self.model_class.__name__} {item_id} by setting {field}={value}")
                         break # Assume one field is enough for soft delete
                         
                if not updated:
                     logger.warning(f"Soft delete failed for {self.model_class.__name__} {item_id}: No suitable status/is_active field found or already deleted.")
                     # Return False or attempt hard delete? Depends on policy.
                     return False # Indicate soft delete wasn't possible
                else:
                     # Flush the status change
                     await self.db.flush()
                     logger.info(f"Soft deleted {self.model_class.__name__} record with ID: {item_id}")
                     return True
            else:
                # Perform hard delete
                await self.db.delete(item_to_delete)
                await self.db.flush() # Ensure delete is executed
                logger.info(f"Hard deleted {self.model_class.__name__} record with ID: {item_id}")
                return True

        except Exception as e:
            logger.error(f"Error deleting {self.model_class.__name__} record with ID {item_id}: {e}", exc_info=True)
            # Re-raise to let service layer handle rollback etc.
            raise 