"""
캐싱 시스템
성능 최적화를 위한 다중 계층 캐싱 구현
"""
from backend.cache.redis_cache import get_redis_client, RedisCache
from backend.cache.memory_cache import MemoryCache

__all__ = ['get_redis_client', 'RedisCache', 'MemoryCache', 'get_cache_manager']

# 캐시 매니저 싱글톤 인스턴스
_cache_manager = None

def get_cache_manager():
    """
    캐시 매니저 인스턴스 반환
    
    Returns:
        CacheManager: 캐시 매니저 인스턴스
    """
    global _cache_manager
    if _cache_manager is None:
        from backend.cache.redis_cache import CacheManager
        _cache_manager = CacheManager()
    return _cache_manager