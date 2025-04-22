from fastapi import Depends, HTTPException, Request, status
from typing import Optional, Callable, Dict, Any
import logging
import time

from backend.core.config import settings
from backend.cache.redis_cache import get_redis_client
from backend.utils.request_context import get_request_attribute

logger = logging.getLogger(__name__)

class RateLimiter:
    """
    API 요청 속도 제한 클래스
    
    엔드포인트별로 요청 속도를 제한합니다.
    """
    
    def __init__(
        self, 
        limit: int = None, 
        window: int = None, 
        key_func: Optional[Callable] = None
    ):
        """
        속도 제한기 초기화
        
        Args:
            limit: 제한 횟수 (기본값: 설정에서 가져옴)
            window: 윈도우 크기 (초) (기본값: 60)
            key_func: 키 생성 함수 (기본값: 파트너 ID + 엔드포인트)
        """
        self.redis = get_redis_client()
        self.enabled = settings.ENABLE_RATE_LIMITING
        self.limit = limit or settings.DEFAULT_RATE_LIMIT
        self.window = window or 60
        self.key_func = key_func
    
    async def __call__(self, request: Request):
        """
        의존성 호출 함수
        
        Args:
            request: FastAPI 요청 객체
            
        Raises:
            HTTPException: 속도 제한 초과 시
        """
        # 속도 제한이 비활성화된 경우
        if not self.enabled:
            return
        
        # 파트너 ID 가져오기
        partner_id = get_request_attribute("partner_id")
        if not partner_id:
            return
        
        # 속도 제한 키 생성
        if self.key_func:
            key = self.key_func(request)
        else:
            # 기본 키: 파트너 ID + 요청 경로
            key = f"rate_limit:endpoint:{partner_id}:{request.url.path}"
        
        # 속도 제한 확인
        is_limited, remaining, reset_time = await self._check_rate_limit(key)
        
        # 제한 초과 시 예외 발생
        if is_limited:
            headers = {
                "X-RateLimit-Limit": str(self.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_time),
                "Retry-After": str(reset_time - int(time.time()))
            }
            
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers=headers
            )
        
        # 요청 컨텍스트에 속도 제한 정보 저장 (응답 헤더용)
        request.state.rate_limit = {
            "limit": self.limit,
            "remaining": remaining,
            "reset": reset_time
        }
    
    async def _check_rate_limit(self, key: str) -> tuple[bool, int, int]:
        """
        속도 제한 확인
        
        Args:
            key: 속도 제한 키
            
        Returns:
            tuple[bool, int, int]: (제한 초과 여부, 남은 요청 수, 리셋 시간)
        """
        # 현재 시간
        current_time = int(time.time())
        
        # 윈도우 시작 시간
        window_start = current_time - (current_time % self.window)
        
        # 윈도우 키
        window_key = f"{key}:{window_start}"
        
        # 현재 카운트 가져오기 및 증가
        count = await self.redis.incr(window_key)
        
        # 첫 번째 요청인 경우 만료 시간 설정
        if count == 1:
            await self.redis.expire(window_key, self.window)
        
        # 리셋 시간
        reset_time = window_start + self.window
        
        # 남은 요청 수
        remaining = max(0, self.limit - count)
        
        # 제한 초과 여부
        is_limited = count > self.limit
        
        return is_limited, remaining, reset_time

def rate_limit(
    limit: Optional[int] = None,
    window: Optional[int] = None,
    key_func: Optional[Callable] = None
):
    """
    속도 제한 의존성 생성기
    
    Args:
        limit: 제한 횟수
        window: 윈도우 크기 (초)
        key_func: 키 생성 함수
        
    Returns:
        Callable: 의존성 함수
    """
    return RateLimiter(limit, window, key_func)