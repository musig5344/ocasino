"""
Redis 캐시 구현
Redis를 사용한 분산 캐싱 기능 제공
"""
import json
import logging
import asyncio
from typing import Any, Optional, Dict, Union, List, Tuple
from datetime import datetime, timedelta

import redis.asyncio as redis
from redis.exceptions import ConnectionError, RedisError

from backend.core.config import settings

logger = logging.getLogger(__name__)

# Redis 클라이언트 인스턴스
_redis_client = None

async def get_redis_client() -> redis.Redis:
    """
    Redis 클라이언트 인스턴스 반환
    
    Returns:
        redis.Redis: Redis 클라이언트
    """
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                retry_on_timeout=True
            )
            # 연결 테스트
            await _redis_client.ping()
            logger.info(f"Connected to Redis at {settings.REDIS_URL}")
        except (ConnectionError, RedisError) as e:
            logger.error(f"Failed to connect to Redis: {e}")
            # 메모리 캐시로 폴백할 수 있도록 None 반환
            return None
    
    return _redis_client

class RedisCache:
    """Redis 캐시 클래스"""
    
    def __init__(self, prefix: str = "casino"):
        """
        Redis 캐시 초기화
        
        Args:
            prefix: 캐시 키 접두사
        """
        self.prefix = prefix
        self.client = None
    
    async def _get_client(self) -> Optional[redis.Redis]:
        """
        Redis 클라이언트 가져오기
        
        Returns:
            Optional[redis.Redis]: Redis 클라이언트 또는 None
        """
        if self.client is None:
            self.client = await get_redis_client()
        return self.client
    
    def _build_key(self, key: str) -> str:
        """
        캐시 키 생성
        
        Args:
            key: 원본 키
            
        Returns:
            str: 접두사가 포함된 최종 키
        """
        if not self.prefix or key.startswith(f"{self.prefix}:"):
            return key
        return f"{self.prefix}:{key}"
    
    async def get(self, key: str) -> Optional[str]:
        """
        캐시에서 값 조회
        
        Args:
            key: 캐시 키
            
        Returns:
            Optional[str]: 캐시된 값 또는 None
        """
        client = await self._get_client()
        if not client:
            return None
        
        try:
            value = await client.get(self._build_key(key))
            return value
        except Exception as e:
            logger.error(f"Redis get error for key {key}: {e}")
            return None
    
    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """
        캐시에서 JSON 값 조회
        
        Args:
            key: 캐시 키
            
        Returns:
            Optional[Dict[str, Any]]: 캐시된 JSON 값 또는 None
        """
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode JSON for key {key}")
        return None
    
    async def set(
        self, key: str, value: Union[str, Dict[str, Any]], 
        ex: Optional[int] = None, nx: bool = False
    ) -> bool:
        """
        캐시에 값 저장
        
        Args:
            key: 캐시 키
            value: 저장할 값 (문자열 또는 JSON 직렬화 가능 객체)
            ex: 만료 시간 (초)
            nx: True인 경우 키가 없을 때만 설정
            
        Returns:
            bool: 성공 여부
        """
        client = await self._get_client()
        if not client:
            return False
        
        # 값 직렬화
        if not isinstance(value, str):
            try:
                value = json.dumps(value)
            except (TypeError, ValueError) as e:
                logger.error(f"JSON serialization error for key {key}: {e}")
                return False
        
        try:
            result = await client.set(
                self._build_key(key), 
                value, 
                ex=ex,
                nx=nx
            )
            return bool(result)
        except Exception as e:
            logger.error(f"Redis set error for key {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """
        캐시에서 값 삭제
        
        Args:
            key: 캐시 키
            
        Returns:
            bool: 성공 여부
        """
        client = await self._get_client()
        if not client:
            return False
        
        try:
            result = await client.delete(self._build_key(key))
            return bool(result)
        except Exception as e:
            logger.error(f"Redis delete error for key {key}: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """
        캐시에 키가 존재하는지 확인
        
        Args:
            key: 캐시 키
            
        Returns:
            bool: 존재 여부
        """
        client = await self._get_client()
        if not client:
            return False
        
        try:
            result = await client.exists(self._build_key(key))
            return bool(result)
        except Exception as e:
            logger.error(f"Redis exists error for key {key}: {e}")
            return False
    
    async def ttl(self, key: str) -> Optional[int]:
        """
        키의 남은 TTL 조회
        
        Args:
            key: 캐시 키
            
        Returns:
            Optional[int]: 남은 시간(초) 또는 None
        """
        client = await self._get_client()
        if not client:
            return None
        
        try:
            result = await client.ttl(self._build_key(key))
            return result if result > 0 else None
        except Exception as e:
            logger.error(f"Redis TTL error for key {key}: {e}")
            return None
    
    async def keys(self, pattern: str) -> List[str]:
        """
        패턴과 일치하는 모든 키 조회
        
        Args:
            pattern: 검색 패턴
            
        Returns:
            List[str]: 일치하는 키 목록
        """
        client = await self._get_client()
        if not client:
            return []
        
        try:
            full_pattern = self._build_key(pattern)
            return await client.keys(full_pattern)
        except Exception as e:
            logger.error(f"Redis keys error for pattern {pattern}: {e}")
            return []
    
    async def delete_pattern(self, pattern: str) -> int:
        """
        패턴과 일치하는 모든 키 삭제
        
        Args:
            pattern: 검색 패턴
            
        Returns:
            int: 삭제된 키 수
        """
        client = await self._get_client()
        if not client:
            return 0
        
        try:
            keys = await self.keys(pattern)
            if not keys:
                return 0
            
            return await client.delete(*keys)
        except Exception as e:
            logger.error(f"Redis delete pattern error for pattern {pattern}: {e}")
            return 0
    
    async def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """
        키 값 증가
        
        Args:
            key: 캐시 키
            amount: 증가량
            
        Returns:
            Optional[int]: 증가 후 값 또는 None
        """
        client = await self._get_client()
        if not client:
            return None
        
        try:
            if amount == 1:
                return await client.incr(self._build_key(key))
            else:
                return await client.incrby(self._build_key(key), amount)
        except Exception as e:
            logger.error(f"Redis incr error for key {key}: {e}")
            return None
    
    async def get_many(self, keys: List[str]) -> Dict[str, Optional[str]]:
        """
        여러 키의 값 조회
        
        Args:
            keys: 캐시 키 목록
            
        Returns:
            Dict[str, Optional[str]]: 키-값 딕셔너리
        """
        client = await self._get_client()
        if not client:
            return {key: None for key in keys}
        
        try:
            full_keys = [self._build_key(key) for key in keys]
            values = await client.mget(full_keys)
            
            return {key: value for key, value in zip(keys, values)}
        except Exception as e:
            logger.error(f"Redis mget error: {e}")
            return {key: None for key in keys}

class CacheManager:
    """통합 캐시 관리자"""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        """싱글톤 패턴 구현"""
        if cls._instance is None:
            cls._instance = super(CacheManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, prefix: str = "casino"):
        """
        캐시 관리자 초기화
        
        Args:
            prefix: 캐시 키 접두사
        """
        # 싱글톤 패턴: 이미 초기화된 경우 건너뜀
        if getattr(self, "_initialized", False):
            return
        
        self._initialized = True
        self.prefix = prefix
        
        # L1 캐시(메모리) 초기화
        from backend.cache.memory_cache import MemoryCache
        self.memory_cache = MemoryCache(max_size=10000)
        
        # L2 캐시(Redis) 초기화
        self.redis_cache = RedisCache(prefix=prefix)
        
        # 연결 상태
        self._redis_connected = False
        asyncio.create_task(self._check_redis_connection())
    
    async def _check_redis_connection(self):
        """Redis 연결 확인 및 상태 업데이트"""
        client = await self.redis_cache._get_client()
        self._redis_connected = client is not None
    
    def is_connected(self) -> bool:
        """
        Redis 연결 상태 확인
        
        Returns:
            bool: 연결 여부
        """
        return self._redis_connected
    
    async def get(self, key: str, tier: str = "all", default: Any = None) -> Any:
        """
        캐시에서 값 조회
        
        Args:
            key: 캐시 키
            tier: 조회할 캐시 계층 ("l1", "l2", "all")
            default: 기본값 (캐시 미스 시 반환)
            
        Returns:
            Any: 캐시된 값 또는 기본값
        """
        # L1 캐시 조회
        if tier in ["l1", "all"]:
            l1_value = self.memory_cache.get(key)
            if l1_value is not None:
                return l1_value
        
        # L2 캐시 조회
        if tier in ["l2", "all"] and self._redis_connected:
            l2_value = await self.redis_cache.get_json(key)
            if l2_value is not None:
                # L1 캐시 업데이트 (L2에서 가져온 값으로)
                if tier == "all":
                    ttl = await self.redis_cache.ttl(key) or 60  # 기본 1분
                    ttl = min(ttl, 60)  # 최대 1분
                    self.memory_cache.set(key, l2_value, ttl=ttl)
                
                return l2_value
        
        return default
    
    async def set(
        self, key: str, value: Any, ttl: Optional[int] = None, 
        tier: str = "all", nx: bool = False
    ) -> bool:
        """
        캐시에 값 저장
        
        Args:
            key: 캐시 키
            value: 저장할 값
            ttl: TTL (초)
            tier: 저장할 캐시 계층 ("l1", "l2", "all")
            nx: True인 경우 키가 없을 때만 설정
            
        Returns:
            bool: 성공 여부
        """
        success = True
        
        # L1 캐시 저장
        if tier in ["l1", "all"]:
            # L1은 짧은 TTL 사용
            l1_ttl = min(ttl or 300, 60)  # 최대 60초
            self.memory_cache.set(key, value, ttl=l1_ttl)
        
        # L2 캐시 저장
        if tier in ["l2", "all"] and self._redis_connected:
            l2_success = await self.redis_cache.set(key, value, ex=ttl, nx=nx)
            success = success and l2_success
        
        return success
    
    async def delete(self, key: str, tier: str = "all") -> bool:
        """
        캐시에서 값 삭제
        
        Args:
            key: 캐시 키
            tier: 삭제할 캐시 계층 ("l1", "l2", "all")
            
        Returns:
            bool: 성공 여부
        """
        success = True
        
        # L1 캐시 삭제
        if tier in ["l1", "all"]:
            self.memory_cache.delete(key)
        
        # L2 캐시 삭제
        if tier in ["l2", "all"] and self._redis_connected:
            l2_success = await self.redis_cache.delete(key)
            success = success and l2_success
        
        return success
    
    async def delete_pattern(self, pattern: str, tier: str = "all") -> int:
        """
        패턴과 일치하는 모든 키 삭제
        
        Args:
            pattern: 검색 패턴
            tier: 삭제할 캐시 계층 ("l1", "l2", "all")
            
        Returns:
            int: 삭제된 키 수
        """
        deleted_count = 0
        
        # L2 캐시 패턴 삭제 (L1은 패턴 삭제 미지원)
        if tier in ["l2", "all"] and self._redis_connected:
            deleted_count = await self.redis_cache.delete_pattern(pattern)
        
        return deleted_count
    
    async def exists(self, key: str, tier: str = "all") -> bool:
        """
        캐시에 키가 존재하는지 확인
        
        Args:
            key: 캐시 키
            tier: 확인할 캐시 계층 ("l1", "l2", "all")
            
        Returns:
            bool: 존재 여부
        """
        # L1 캐시 확인
        if tier in ["l1", "all"]:
            l1_exists = self.memory_cache.get(key) is not None
            if l1_exists:
                return True
        
        # L2 캐시 확인
        if tier in ["l2", "all"] and self._redis_connected:
            l2_exists = await self.redis_cache.exists(key)
            return l2_exists
        
        return False