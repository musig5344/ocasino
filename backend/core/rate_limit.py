from fastapi import Request, HTTPException, status, Response
from fastapi.responses import JSONResponse
from typing import Dict, Optional, Callable, Union, Tuple, List
import time
import json
import hashlib
import asyncio
import logging
from datetime import datetime
from functools import wraps

from backend.core.config import settings
from backend.cache.redis_cache import get_redis_client
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

class RateLimiter:
    """
    API 요청 속도 제한 클래스
    
    고정 윈도우 또는 슬라이딩 윈도우 알고리즘을 사용하여 API 요청 속도를 제한합니다.
    """
    
    def __init__(self):
        """속도 제한기 초기화"""
        self.redis = get_redis_client()
        self.enabled = settings.ENABLE_RATE_LIMITING
        self.strategy = settings.RATE_LIMIT_STRATEGY
        
        # 엔드포인트별 속도 제한 설정
        self.endpoint_limits = self._load_endpoint_limits()
    
    def _load_endpoint_limits(self) -> Dict[str, Dict[str, int]]:
        """
        엔드포인트별 속도 제한 설정 로드
        
        Returns:
            Dict[str, Dict[str, int]]: 엔드포인트별 속도 제한 설정
        """
        # 엔드포인트별 속도 제한 설정
        # 키: 엔드포인트 패턴, 값: 속도 제한 정보
        return {
            # 인증 관련 엔드포인트 - 더 엄격한 제한
            "^/api/auth/token": {
                "limit": 10,         # 분당 10회
                "window": 60,        # 1분 윈도우
                "block_time": 300    # 제한 초과 시 5분 차단
            },
            # 지갑 관련 엔드포인트
            "^/api/wallet/.*/(deposit|withdraw|bet|win)": {
                "limit": 50,         # 분당 50회
                "window": 60,        # 1분 윈도우
                "block_time": 0      # 차단하지 않음
            },
            # 게임 세션 생성
            "^/api/games/session": {
                "limit": 100,        # 분당 100회
                "window": 60,        # 1분 윈도우
                "block_time": 0      # 차단하지 않음
            },
            # 보고서 생성 - 낮은 제한
            "^/api/reports$": {
                "limit": 20,         # 분당 20회
                "window": 60,        # 1분 윈도우
                "block_time": 0      # 차단하지 않음
            },
            # 기본 API 엔드포인트
            "^/api/": {
                "limit": settings.DEFAULT_RATE_LIMIT,  # 분당 기본 제한 (설정에서 가져옴)
                "window": 60,         # 1분 윈도우
                "block_time": 0       # 차단하지 않음
            }
        }
    
    def _get_limit_for_endpoint(self, path: str) -> Dict[str, int]:
        """
        엔드포인트에 대한 속도 제한 설정 가져오기
        
        Args:
            path: 요청 경로
            
        Returns:
            Dict[str, int]: 속도 제한 설정
        """
        import re
        
        # 엔드포인트 패턴 매칭
        for pattern, limits in self.endpoint_limits.items():
            if re.match(pattern, path):
                return limits
        
        # 기본 제한 반환
        return self.endpoint_limits["^/api/"]
    
    def _generate_key(self, request: Request, key_type: str = "ip") -> str:
        """
        속도 제한 키 생성
        
        Args:
            request: 요청 객체
            key_type: 키 유형 (ip, api_key, endpoint)
            
        Returns:
            str: 속도 제한 키
        """
        path = request.url.path
        
        if key_type == "ip":
            # IP 주소 기반 키
            client_ip = self._get_client_ip(request)
            return f"rate_limit:ip:{client_ip}:{path}"
        elif key_type == "api_key":
            # API 키 기반 키
            api_key = request.headers.get("X-API-Key", "")
            if not api_key:
                return self._generate_key(request, "ip")
            
            # API 키 해싱 (로그에 전체 키가 노출되지 않도록)
            hashed_key = hashlib.sha256(api_key.encode()).hexdigest()[:16]
            return f"rate_limit:api_key:{hashed_key}:{path}"
        elif key_type == "endpoint":
            # 엔드포인트 기반 키
            return f"rate_limit:endpoint:{path}"
        else:
            # 기본 키 (IP 기반)
            return self._generate_key(request, "ip")
    
    def _get_client_ip(self, request: Request) -> str:
        """
        클라이언트 IP 주소 가져오기
        
        Args:
            request: 요청 객체
            
        Returns:
            str: IP 주소
        """
        # X-Forwarded-For 헤더를 확인 (프록시 뒤에 있는 경우)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # 첫 번째 IP만 사용 (쉼표로 구분된 목록일 수 있음)
            return forwarded_for.split(",")[0].strip()
        
        # 클라이언트 호스트 사용
        return request.client.host
    
    async def _is_rate_limited_fixed_window(
        self,
        key: str,
        limit: int,
        window: int
    ) -> Tuple[bool, int, int, int]:
        """
        고정 윈도우 알고리즘을 사용한 속도 제한 확인
        
        Args:
            key: 속도 제한 키
            limit: 제한 횟수
            window: 윈도우 크기 (초)
            
        Returns:
            Tuple[bool, int, int, int]: (제한 여부, 현재 횟수, 제한 횟수, 리셋 시간)
        """
        # 현재 시간 가져오기
        current_time = int(time.time())
        
        # 윈도우 시작 시간 계산
        window_start = current_time - (current_time % window)
        
        # 윈도우 키 생성
        window_key = f"{key}:{window_start}"
        
        # 현재 카운트 가져오기
        count = await self.redis.incr(window_key)
        
        # 첫 번째 요청인 경우 만료 시간 설정
        if count == 1:
            await self.redis.expire(window_key, window)
        
        # TTL 확인
        ttl = await self.redis.ttl(window_key)
        if ttl < 0:
            ttl = window
        
        # 제한 확인
        is_limited = count > limit
        
        return is_limited, count, limit, window_start + window
    
    async def _is_rate_limited_sliding_window(
        self,
        key: str,
        limit: int,
        window: int
    ) -> Tuple[bool, int, int, int]:
        """
        슬라이딩 윈도우 알고리즘을 사용한 속도 제한 확인
        
        Args:
            key: 속도 제한 키
            limit: 제한 횟수
            window: 윈도우 크기 (초)
            
        Returns:
            Tuple[bool, int, int, int]: (제한 여부, 현재 횟수, 제한 횟수, 리셋 시간)
        """
        # 현재 시간 가져오기
        current_time = int(time.time() * 1000)  # 밀리초 단위
        
        # 윈도우 시작 시간 계산
        window_start = current_time - (window * 1000)
        
        # 요청 시간 추가
        await self.redis.zadd(key, {str(current_time): current_time})
        
        # 만료 시간 설정
        await self.redis.expire(key, window * 2)
        
        # 윈도우 내 요청 수 계산
        count = await self.redis.zcount(key, window_start, "+inf")
        
        # 오래된 요청 제거
        await self.redis.zremrangebyscore(key, 0, window_start)
        
        # 제한 확인
        is_limited = count > limit
        
        # 리셋 시간 계산
        if count > 0:
            oldest = await self.redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                oldest_time = int(oldest[0][1])
                reset_time = oldest_time + (window * 1000)
                reset_seconds = int((reset_time - current_time) / 1000) + 1
            else:
                reset_seconds = window
        else:
            reset_seconds = window
        
        return is_limited, count, limit, int(time.time()) + reset_seconds
    
    async def _is_blocked(self, key: str) -> Tuple[bool, int]:
        """
        차단 여부 확인
        
        Args:
            key: 속도 제한 키
            
        Returns:
            Tuple[bool, int]: (차단 여부, 남은 시간)
        """
        # 차단 키
        block_key = f"{key}:blocked"
        
        # 차단 여부 확인
        ttl = await self.redis.ttl(block_key)
        
        return ttl > 0, ttl
    
    async def _block_key(self, key: str, block_time: int) -> None:
        """
        키 차단
        
        Args:
            key: 속도 제한 키
            block_time: 차단 시간 (초)
        """
        if block_time <= 0:
            return
        
        # 차단 키
        block_key = f"{key}:blocked"
        
        # 차단 설정
        await self.redis.set(block_key, 1, ex=block_time)
    
    async def is_rate_limited(
        self,
        request: Request,
        response: Response,
        key_type: str = "api_key"
    ) -> bool:
        """
        속도 제한 확인
        
        Args:
            request: 요청 객체
            response: 응답 객체
            key_type: 키 유형 (ip, api_key, endpoint)
            
        Returns:
            bool: 제한 여부
        """
        # 속도 제한이 비활성화된 경우
        if not self.enabled:
            return False
        
        # 백오피스 요청은 제한하지 않음
        if request.url.path.startswith("/admin"):
            return False
        
        # 건강 상태 확인 요청은 제한하지 않음
        if request.url.path.startswith("/api/health"):
            return False
        
        # 엔드포인트에 대한 제한 가져오기
        limits = self._get_limit_for_endpoint(request.url.path)
        limit = limits["limit"]
        window = limits["window"]
        block_time = limits["block_time"]
        
        # 속도 제한 키 생성
        key = self._generate_key(request, key_type)
        
        # 차단 여부 확인
        is_blocked, block_ttl = await self._is_blocked(key)
        if is_blocked:
            # 응답 헤더 설정
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = "0"
            response.headers["X-RateLimit-Reset"] = str(int(time.time()) + block_ttl)
            response.headers["Retry-After"] = str(block_ttl)
            return True
        
        # 속도 제한 확인
        if self.strategy == "sliding-window":
            is_limited, count, limit, reset_time = await self._is_rate_limited_sliding_window(key, limit, window)
        else:
            is_limited, count, limit, reset_time = await self._is_rate_limited_fixed_window(key, limit, window)
        
        # 응답 헤더 설정
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        response.headers["X-RateLimit-Reset"] = str(reset_time)
        
        # 제한 초과 시 차단
        if is_limited:
            # 차단 시간이 설정된 경우에만 차단
            if block_time > 0:
                await self._block_key(key, block_time)
                
                # Retry-After 헤더 설정
                response.headers["Retry-After"] = str(block_time)
            else:
                # 차단하지 않고 다음 윈도우까지 대기 시간 계산
                retry_after = reset_time - int(time.time())
                if retry_after > 0:
                    response.headers["Retry-After"] = str(retry_after)
        
        return is_limited


# 싱글톤 인스턴스
_rate_limiter = None

def get_rate_limiter() -> RateLimiter:
    """
    속도 제한기 싱글톤 인스턴스 가져오기
    
    Returns:
        RateLimiter: 속도 제한기 객체
    """
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


async def rate_limit_middleware(request: Request, call_next):
    """
    속도 제한 미들웨어
    
    Args:
        request: 요청 객체
        call_next: 다음 미들웨어 호출 함수
        
    Returns:
        응답 객체
    """
    # 속도 제한 확인이 필요한 경로인지 확인
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    
    # 응답 객체 생성
    response = Response()
    
    # 속도 제한기 가져오기
    rate_limiter = get_rate_limiter()
    
    # 속도 제한 확인
    is_limited = await rate_limiter.is_rate_limited(request, response)
    
    if is_limited:
        # 속도 제한 초과 응답
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": {
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": "Rate limit exceeded. Please try again later."
                }
            },
            headers=dict(response.headers)
        )
    
    # 다음 미들웨어 호출
    response = await call_next(request)
    
    # 응답 헤더 복사
    for key, value in response.headers.items():
        if key.startswith("X-RateLimit"):
            response.headers[key] = value
    
    return response


def rate_limit(
    limit: Optional[int] = None,
    window: Optional[int] = None,
    key_func: Optional[Callable] = None
):
    """
    속도 제한 데코레이터
    
    Args:
        limit: 제한 횟수 (기본값: 설정에서 가져옴)
        window: 윈도우 크기 (초) (기본값: 60)
        key_func: 키 생성 함수 (기본값: IP 주소)
        
    Returns:
        Callable: 데코레이터 함수
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # request 객체 가져오기
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            if not request:
                # request 객체가 없으면 원래 함수 호출
                return await func(*args, **kwargs)
            
            # 응답 객체 생성
            response = Response()
            
            # 속도 제한기 가져오기
            rate_limiter = get_rate_limiter()
            
            # 키 생성
            if key_func:
                key = key_func(request)
            else:
                key = rate_limiter._generate_key(request, "api_key")
            
            # 제한 및 윈도우 설정
            actual_limit = limit or settings.DEFAULT_RATE_LIMIT
            actual_window = window or 60
            
            # 차단 여부 확인
            is_blocked, block_ttl = await rate_limiter._is_blocked(key)
            if is_blocked:
                # 응답 헤더 설정
                headers = {
                    "X-RateLimit-Limit": str(actual_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + block_ttl),
                    "Retry-After": str(block_ttl)
                }
                
                # 속도 제한 초과 응답
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": "Rate limit exceeded. Please try again later."
                        }
                    },
                    headers=headers
                )
            
            # 속도 제한 확인
            if rate_limiter.strategy == "sliding-window":
                is_limited, count, _, reset_time = await rate_limiter._is_rate_limited_sliding_window(
                    key, actual_limit, actual_window
                )
            else:
                is_limited, count, _, reset_time = await rate_limiter._is_rate_limited_fixed_window(
                    key, actual_limit, actual_window
                )
            
            # 응답 헤더 설정
            headers = {
                "X-RateLimit-Limit": str(actual_limit),
                "X-RateLimit-Remaining": str(max(0, actual_limit - count)),
                "X-RateLimit-Reset": str(reset_time)
            }
            
            if is_limited:
                # 재시도 시간 계산
                retry_after = reset_time - int(time.time())
                if retry_after > 0:
                    headers["Retry-After"] = str(retry_after)
                
                # 속도 제한 초과 응답
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": "Rate limit exceeded. Please try again later."
                        }
                    },
                    headers=headers
                )
            
            # 원래 함수 호출
            response = await func(*args, **kwargs)
            
            # 응답 헤더 추가
            for key, value in headers.items():
                response.headers[key] = value
            
            return response
        
        return wrapper
    
    return decorator