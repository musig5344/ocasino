"""
Redis 캐시 구현
Redis를 사용한 분산 캐싱 기능 제공
"""
import json
import logging
import asyncio
from typing import Any, Optional, Dict, Union, List, Tuple, Callable, Coroutine
from datetime import datetime, timedelta
import functools
import hashlib
import inspect
from urllib.parse import urlparse
from uuid import UUID

import redis.asyncio as redis
from redis.exceptions import ConnectionError, RedisError

from backend.core.config import settings

logger = logging.getLogger(__name__)

# Redis 클라이언트 인스턴스
_redis_client = None
_redis_cluster_client = None # 클러스터 클라이언트 추가

async def get_redis_client() -> redis.Redis:
    """
    Redis 클라이언트 인스턴스 반환
    
    Returns:
        redis.Redis: Redis 클라이언트
    """
    global _redis_client
    if _redis_client is None:
        try:
            # URL이 없거나 잘못된 형식이면 기본값 사용
            redis_url = getattr(settings, 'REDIS_URL', "redis://127.0.0.1:6379/0")
            
            # URL이 redis://, rediss://, unix:// 로 시작하는지 확인
            parsed_url = urlparse(redis_url)
            if parsed_url.scheme not in ['redis', 'rediss', 'unix']:
                logger.warning(f"Invalid Redis URL scheme: {parsed_url.scheme}. Using default URL.")
                redis_url = "redis://127.0.0.1:6379/0"
            
            _redis_client = redis.from_url(
                redis_url,
                decode_responses=False,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                retry_on_timeout=True
            )
            # 연결 테스트
            await _redis_client.ping()
            logger.info(f"Connected to Redis at {redis_url}")
        except (ConnectionError, RedisError, TimeoutError) as e:
            logger.error(f"Failed to connect to Redis: {e}")
            # 클라이언트 생성 실패 시 None 반환
            _redis_client = None
            return None
        except Exception as e:
            logger.exception(f"Unexpected error connecting to Redis: {e}")
            _redis_client = None
            return None

    return _redis_client

async def get_redis_cluster_client():
    """
    Redis 클러스터 클라이언트 가져오기
    """
    from redis.asyncio import RedisCluster
    
    global _redis_cluster_client
    if _redis_cluster_client is None:
        try:
            # 클러스터 URL 확인
            cluster_url = getattr(settings, 'REDIS_CLUSTER_URL', None)
            if not cluster_url:
                logger.warning("Redis Cluster URL not configured")
                return None
            
            _redis_cluster_client = await RedisCluster.from_url(
                cluster_url, 
                decode_responses=True
            )
            await _redis_cluster_client.ping()
            logger.info("Connected to Redis Cluster")
        except Exception as e:
            logger.error(f"Failed to connect to Redis Cluster: {e}")
            return None
    
    return _redis_cluster_client

class RedisCache:
    """Redis 캐시 클래스 (태그 기능 추가)"""
    
    def __init__(self, prefix: str = "cache"):
        """
        Redis 캐시 초기화
        
        Args:
            prefix: 데이터 캐시 키 접두사
        """
        self.prefix = prefix
        self.client = None
        self.lock_prefix = "lock"
        self.tag_prefix = "tag"
    
    async def _get_client(self) -> Optional[redis.Redis]:
        """
        Redis 클라이언트 가져오기 (연결 실패 시 None 반환)
        """
        if self.client is None:
            try:
                self.client = await get_redis_client()
                if self.client:
                    # ping이 성공하면 연결 상태 확인
                    await self.client.ping()
            except Exception:
                self.client = None
        return self.client
    
    def _build_key(self, key: str) -> str:
        """데이터 캐시 키 생성"""
        return f"{self.prefix}:{key}"
    
    def _build_lock_key(self, key: str) -> str:
        """Lock 키 생성"""
        return f"{self.lock_prefix}:{self._build_key(key)}"
    
    def _build_tag_key(self, tag: str) -> str:
        """태그 키 생성"""
        return f"{self.tag_prefix}:{tag}"
    
    def _serialize(self, value: Any) -> bytes:
        """값을 JSON bytes로 직렬화 (Pydantic, datetime, UUID 처리 추가)"""
        try:
            def default_serializer(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                if isinstance(obj, UUID):
                    return str(obj) # UUID를 문자열로 변환
                # SQLAlchemy 모델 등을 위한 기본 처리 시도 (실패 가능성 있음)
                if hasattr(obj, '__dict__') and not isinstance(obj, type):
                    # 기본적인 __dict__ 시도 (SQLAlchemy는 복잡할 수 있음)
                    # _sa_instance_state 와 같은 내부 속성 제외
                    return {k: v for k, v in obj.__dict__.items() if not k.startswith('_sa_') and not k.startswith('__')}
                raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

            # Pydantic v2 모델 확인
            if hasattr(value, 'model_dump_json') and callable(value.model_dump_json):
                # Pydantic 모델 자체의 직렬화 사용 (UUID/datetime 포함)
                return value.model_dump_json().encode('utf-8')
            # Pydantic v1 모델 확인
            elif hasattr(value, 'dict') and callable(value.dict):
                 return json.dumps(value.dict(), default=default_serializer).encode('utf-8')
            # 다른 타입에 대한 기본 json.dumps (커스텀 핸들러 사용)
            else:
                return json.dumps(value, default=default_serializer).encode('utf-8')
        except TypeError as e:
            logger.error(f"Serialization failed: {e}. Value type: {type(value)}")
            raise # 직렬화 실패 시 에러 재발생시켜 캐싱 중단
    
    def _deserialize(self, value: Optional[bytes]) -> Any:
        """JSON bytes를 원래 값으로 역직렬화"""
        if value is None:
            return None
        try:
            return json.loads(value.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(f"Failed to deserialize cached value: {value[:100]}...")
            return None
    
    async def get(self, key: str) -> Any:
        """
        캐시에서 값 조회 (역직렬화 포함)
        
        Args:
            key: 원본 키
            
        Returns:
            Any: 캐시된 값 또는 None
        """
        client = await self._get_client()
        if not client:
            return None

        cache_key = self._build_key(key)
        try:
            value_bytes = await client.get(cache_key)
            return self._deserialize(value_bytes)
        except RedisError as e:
            logger.error(f"Redis get error for key {cache_key}: {e}")
            return None
    
    async def set_with_tags(
        self, key: str, value: Any,
        tags: Optional[List[str]] = None, ex: Optional[int] = None
    ) -> bool:
        """
        태그와 함께 캐시에 값 저장 (파이프라인 사용)
        
        Args:
            key: 원본 키
            value: 저장할 값
            tags: 연결할 태그 목록
            ex: 만료 시간 (초)
            
        Returns:
            bool: 성공 여부
        """
        client = await self._get_client()
        if not client:
            return False

        cache_key = self._build_key(key)
        try:
            serialized_value = self._serialize(value)

            async with client.pipeline(transaction=True) as pipe:
                pipe.set(cache_key, serialized_value, ex=ex)

                if tags:
                    for tag in tags:
                        tag_key = self._build_tag_key(tag)
                        pipe.sadd(tag_key, cache_key)
                        if ex:
                            pipe.expire(tag_key, ex + 60)

                results = await pipe.execute()
                return all(results)
        except RedisError as e:
            logger.error(f"Redis set_with_tags error for key {cache_key}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error during set_with_tags for key {cache_key}: {e}")
            return False
    
    async def delete(self, *keys: str) -> int:
        """
        캐시에서 하나 이상의 키 삭제 (태그 매핑은 제거 안 함)
        
        Args:
            *keys: 삭제할 원본 키 목록
            
        Returns:
            int: 삭제된 키의 수
        """
        client = await self._get_client()
        if not client or not keys:
            return 0

        cache_keys = [self._build_key(key) for key in keys]
        try:
            return await client.delete(*cache_keys)
        except RedisError as e:
            logger.error(f"Redis delete error for keys {keys}: {e}")
            return 0
    
    async def invalidate_by_tag(self, *tags: str) -> int:
        """
        특정 태그와 연결된 모든 캐시 키를 무효화 (파이프라인 사용)
        
        Args:
            *tags: 무효화할 태그 목록
            
        Returns:
            int: 삭제된 총 키의 수 (근사치)
        """
        client = await self._get_client()
        if not client or not tags:
            return 0

        total_deleted = 0
        tag_keys = [self._build_tag_key(tag) for tag in tags]

        try:
            async with client.pipeline(transaction=False) as pipe:
                cache_keys_to_delete = set()
                for tag_key in tag_keys:
                    members = await client.smembers(tag_key)
                    if members:
                        cache_keys_to_delete.update(members) # 바이트 문자열 그대로 추가

                if not cache_keys_to_delete:
                    if tag_keys:
                        await client.delete(*tag_keys) # 태그 키 자체 삭제
                    return 0

                # Delete actual cache entries
                if cache_keys_to_delete:
                    pipe.delete(*cache_keys_to_delete)

                # Delete tag keys
                pipe.delete(*tag_keys)

                results = await pipe.execute()
                
                # Calculate deleted count (approximation as some keys might not exist)
                # The first result of the pipeline execution corresponds to the deletion of cache keys
                if results and isinstance(results[0], int):
                    total_deleted = results[0]

            logger.info(f"Invalidated {total_deleted} cache entries for tags: {tags}")
            return total_deleted
        except RedisError as e:
            logger.error(f"Redis invalidate_by_tag error for tags {tags}: {e}")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error during invalidate_by_tag for tags {tags}: {e}")
            return 0
            
    async def ttl(self, key: str) -> Optional[int]:
        """
        키의 TTL(Time To Live) 조회
        
        Args:
            key: 원본 키
            
        Returns:
            Optional[int]: TTL(초) 또는 None(키 없음)
        """
        client = await self._get_client()
        if not client:
            return None
            
        cache_key = self._build_key(key)
        try:
            ttl = await client.ttl(cache_key)
            # -2는 키가 없음, -1은 키는 있지만 TTL이 설정되지 않음
            if ttl == -2:
                return None
            elif ttl == -1:
                return None  # 무기한 (영구)
            return ttl
        except RedisError as e:
            logger.error(f"Redis TTL error for key {cache_key}: {e}")
            return None
            
    async def exists(self, key: str) -> bool:
        """
        키가 존재하는지 확인
        
        Args:
            key: 원본 키
            
        Returns:
            bool: 존재 여부
        """
        client = await self._get_client()
        if not client:
            return False
            
        cache_key = self._build_key(key)
        try:
            return bool(await client.exists(cache_key))
        except RedisError as e:
            logger.error(f"Redis exists error for key {cache_key}: {e}")
            return False
            
    async def delete_pattern(self, pattern: str) -> int:
        """
        패턴과 일치하는 모든 키 삭제
        
        Args:
            pattern: 검색 패턴 (예: "user:*")
            
        Returns:
            int: 삭제된 키의 수
        """
        client = await self._get_client()
        if not client:
            return 0
            
        # 패턴에 접두사 추가 (필요시)
        if not pattern.startswith(f"{self.prefix}:"):
            full_pattern = f"{self.prefix}:{pattern}"
        else:
            full_pattern = pattern
            
        try:
            # 패턴과 일치하는 모든 키 검색
            cursor = 0
            deleted_count = 0
            
            while True:
                cursor, keys = await client.scan(cursor, match=full_pattern, count=100)
                if keys:
                    deleted = await client.delete(*keys)
                    deleted_count += deleted
                
                # 더 이상 키가 없으면 종료
                if cursor == 0:
                    break
                    
            return deleted_count
        except RedisError as e:
            logger.error(f"Redis delete_pattern error for pattern {full_pattern}: {e}")
            return 0

# Cache Decorator
def cache_result(
    key_prefix: str,
    ttl: Optional[int] = None,
    use_args_in_key: bool = True,
    use_kwargs_in_key: bool = True,
    tags: Optional[List[str]] = None
):
    """
    비동기 함수의 결과를 Redis에 캐싱하는 데코레이터.

    Args:
        key_prefix: 캐시 키의 접두사. 함수 이름 앞에 붙습니다.
        ttl: 캐시 만료 시간(초). None이면 만료되지 않습니다.
        use_args_in_key: 함수의 위치 인수를 캐시 키 생성에 사용할지 여부.
        use_kwargs_in_key: 함수의 키워드 인수를 캐시 키 생성에 사용할지 여부.
        tags: 캐시 항목에 연결할 태그 목록.
    """
    def decorator(func: Callable[..., Coroutine]):
        cache = RedisCache() # 데코레이터 내에서 RedisCache 인스턴스 생성

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 캐시 클라이언트 가져오기 시도
            client = await cache._get_client()
            if not client:
                # Redis 연결 실패 시 캐싱 없이 함수 직접 실행
                logger.warning(f"Redis connection failed for caching {func.__name__}. Executing function directly.")
                return await func(*args, **kwargs)

            # 캐시 키 생성
            key_parts = [key_prefix, func.__name__]
            
            # self 또는 cls 인자 제외 (메서드인 경우)
            arg_offset = 0
            if inspect.iscoroutinefunction(func) or inspect.isfunction(func):
                 sig = inspect.signature(func)
                 if sig.parameters:
                     first_param_name = next(iter(sig.parameters))
                     if first_param_name == 'self' or first_param_name == 'cls':
                         arg_offset = 1 # Skip self/cls if it's the first arg

            if use_args_in_key:
                # args 튜플의 arg_offset 이후 요소들을 문자열로 변환하여 추가
                key_parts.extend(map(str, args[arg_offset:]))

            if use_kwargs_in_key:
                 # kwargs 딕셔너리의 항목들을 정렬하여 문자열로 변환 후 추가
                 # 키를 기준으로 정렬하여 순서에 상관없이 동일한 키가 생성되도록 함
                sorted_kwargs = sorted(kwargs.items())
                key_parts.extend([f"{k}={v}" for k, v in sorted_kwargs])

            raw_key = ":".join(key_parts)
            # 해시 함수를 사용하여 키 길이 관리 및 잠재적 특수 문자 문제 방지
            cache_key = hashlib.sha256(raw_key.encode()).hexdigest()

            # 1. 캐시 조회
            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for key: {cache_key} (raw: {raw_key})")
                return cached_value

            # 2. 캐시 미스: 함수 실행
            logger.debug(f"Cache miss for key: {cache_key} (raw: {raw_key}). Executing function {func.__name__}.")
            result = await func(*args, **kwargs)

            # 3. 결과 캐싱 (오류 발생 시 캐싱하지 않음)
            if result is not None: # None이 아닌 결과만 캐싱 (오류 상황 등 고려)
                try:
                    success = await cache.set_with_tags(
                        cache_key, result, tags=tags, ex=ttl
                    )
                    if success:
                         logger.debug(f"Cached result for key: {cache_key} with ttl {ttl} and tags {tags}")
                    else:
                        logger.warning(f"Failed to cache result for key: {cache_key}")
                except Exception as e:
                     logger.error(f"Error caching result for key {cache_key}: {e}")

            return result
        return wrapper
    return decorator

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
            l2_value = await self.redis_cache.get(key)
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
        tier: str = "all", nx: bool = False,
        tags: Optional[List[str]] = None
    ) -> bool:
        """
        캐시에 값 저장
        
        Args:
            key: 캐시 키
            value: 저장할 값
            ttl: TTL (초)
            tier: 저장할 캐시 계층 ("l1", "l2", "all")
            nx: True인 경우 키가 없을 때만 설정
            tags: 태그 목록
            
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
            l2_success = await self.redis_cache.set_with_tags(key, value, tags=tags, ex=ttl)
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