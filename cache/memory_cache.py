"""
메모리 캐시 구현
인메모리 캐싱 기능 제공 (단일 서버에서 사용)
"""
import time
import logging
import threading
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class MemoryCache:
    """인메모리 캐시 클래스"""
    
    def __init__(self, max_size: int = 10000, cleanup_interval: int = 60):
        """
        인메모리 캐시 초기화
        
        Args:
            max_size: 최대 캐시 항목 수
            cleanup_interval: 만료된 항목 정리 간격(초)
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._max_size = max_size
        self._cleanup_interval = cleanup_interval
        self._lock = threading.RLock()
        
        # 클린업 타이머 시작
        self._start_cleanup_timer()
    
    def _start_cleanup_timer(self):
        """주기적으로 만료된 항목 정리 타이머 시작"""
        def cleanup():
            self._remove_expired()
            # 재귀적으로 다음 타이머 설정
            timer = threading.Timer(self._cleanup_interval, cleanup)
            timer.daemon = True
            timer.start()
        
        # 첫 타이머 시작
        timer = threading.Timer(self._cleanup_interval, cleanup)
        timer.daemon = True
        timer.start()
    
    def _remove_expired(self):
        """만료된 캐시 항목 정리"""
        with self._lock:
            now = time.time()
            expired_keys = [
                key for key, value in self._cache.items()
                if value.get('expiry') and value['expiry'] < now
            ]
            
            for key in expired_keys:
                del self._cache[key]
            
            if expired_keys:
                logger.debug(f"Removed {len(expired_keys)} expired items from memory cache")
    
    def _check_size_limit(self):
        """캐시 크기 제한 확인 및 처리 (LRU 정책)"""
        if len(self._cache) >= self._max_size:
            # 가장 오래 사용되지 않은 항목 찾기
            oldest_key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].get('last_access', 0)
            )
            # 제거
            del self._cache[oldest_key]
            logger.debug(f"Removed oldest item from memory cache: {oldest_key}")
    
    def get(self, key: str) -> Optional[Any]:
        """
        캐시에서 값 조회
        
        Args:
            key: 캐시 키
            
        Returns:
            Optional[Any]: 캐시된 값 또는 None (없거나 만료된 경우)
        """
        with self._lock:
            if key not in self._cache:
                return None
            
            cache_item = self._cache[key]
            now = time.time()
            
            # 만료 확인
            if 'expiry' in cache_item and cache_item['expiry'] < now:
                del self._cache[key]
                return None
            
            # 마지막 접근 시간 업데이트 (LRU)
            cache_item['last_access'] = now
            
            return cache_item['value']
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        캐시에 값 저장
        
        Args:
            key: 캐시 키
            value: 저장할 값
            ttl: TTL (초) - 미지정 시 무기한 저장
            
        Returns:
            bool: 성공 여부
        """
        with self._lock:
            # 크기 제한 확인
            if key not in self._cache:
                self._check_size_limit()
            
            # 만료 시간 계산
            expiry = time.time() + ttl if ttl else None
            
            # 캐시 항목 저장
            self._cache[key] = {
                'value': value,
                'expiry': expiry,
                'last_access': time.time(),
                'created_at': time.time()
            }
            
            return True
    
    def delete(self, key: str) -> bool:
        """
        캐시에서 항목 삭제
        
        Args:
            key: 삭제할 캐시 키
            
        Returns:
            bool: 성공 여부 (키가 존재했는지)
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> bool:
        """
        모든 캐시 항목 삭제
        
        Returns:
            bool: 성공 여부
        """
        with self._lock:
            self._cache.clear()
            return True
    
    def get_stats(self) -> Dict[str, Any]:
        """
        캐시 통계 정보 조회
        
        Returns:
            Dict[str, Any]: 통계 정보
        """
        with self._lock:
            total_items = len(self._cache)
            now = time.time()
            expired_items = sum(
                1 for item in self._cache.values()
                if item.get('expiry') and item['expiry'] < now
            )
            
            return {
                'total_items': total_items,
                'expired_items': expired_items,
                'max_size': self._max_size,
                'usage_percent': (total_items / self._max_size) * 100 if self._max_size > 0 else 0
            }