from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from typing import Dict, Optional, Callable, Union
import time
import logging
from datetime import datetime

from backend.core.config import settings
from backend.utils.request_context import get_request_attribute
from backend.cache.redis_cache import get_redis_client

logger = logging.getLogger(__name__)

class RateLimitMiddleware:
    """
    요청 속도 제한 미들웨어
    
    파트너 및 엔드포인트별로 API 요청 속도를 제한합니다.
    """
    
    def __init__(self):
        """미들웨어 초기화"""
        self.redis = get_redis_client()
        self.enabled = settings.ENABLE_RATE_LIMITING
        self.strategy = settings.RATE_LIMIT_STRATEGY
        
        # 엔드포인트별 속도 제한 설정
        self.endpoint_limits = self._load_endpoint_limits()
    
    def _load_endpoint_limits(self) -> Dict[str, Dict[str, int]]:
        """엔드포인트별 속도 제한 설정 로드"""
        import re
        
        # 설정에서 속도 제한 로드 또는 기본값 사용
        return {
            # 인증 관련 엔드포인트 - 더 엄격한 제한
            r"^/api/auth/token": {
                "limit": 10,         # 분당 10회
                "window": 60,        # 1분 윈도우
                "block_time": 300    # 제한 초과 시 5분 차단
            },
            # 지갑 관련 엔드포인트
            r"^/api/wallet/.*/(deposit|withdraw|bet|win)": {
                "limit": 50,         # 분당 50회
                "window": 60,        # 1분 윈도우
                "block_time": 0      # 차단하지 않음
            },
            # 게임 세션 생성
            r"^/api/games/session": {
                "limit": 100,        # 분당 100회
                "window": 60,        # 1분 윈도우
                "block_time": 0      # 차단하지 않음
            },
            # 보고서 생성 - 낮은 제한
            r"^/api/reports$": {
                "limit": 20,         # 분당 20회
                "window": 60,        # 1분 윈도우
                "block_time": 0      # 차단하지 않음
            },
            # 기본 API 엔드포인트
            r"^/api/": {
                "limit": settings.DEFAULT_RATE_LIMIT,  # 분당 기본 제한
                "window": 60,         # 1분 윈도우
                "block_time": 0       # 차단하지 않음
            }
        }
    
    def _get_limit_for_endpoint(self, path: str) -> Dict[str, int]:
        """엔드포인트에 대한 속도 제한 설정 가져오기"""
        import re
        
        # 엔드포인트 패턴 매칭
        for pattern, limits in self.endpoint_limits.items():
            if re.match(pattern, path):
                return limits
        
        # 기본 제한 반환
        return self.endpoint_limits[r"^/api/"]
    
    async def _is_rate_limited(self, key: str, limit: int, window: int) -> tuple[bool, int, int, int]:
        """속도 제한 확인"""
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
    
    async def _is_blocked(self, key: str) -> tuple[bool, int]:
        """차단 여부 확인"""
        # 차단 키
        block_key = f"{key}:blocked"
        
        # 차단 여부 확인
        ttl = await self.redis.ttl(block_key)
        
        return ttl > 0, ttl
    
    async def _block_key(self, key: str, block_time: int) -> None:
        """키 차단"""
        if block_time <= 0:
            return
        
        # 차단 키
        block_key = f"{key}:blocked"
        
        # 차단 설정
        await self.redis.set(block_key, 1, ex=block_time)
    
    async def __call__(self, request: Request, call_next: Callable):
        """미들웨어 처리 로직"""
        # 속도 제한이 비활성화된 경우
        if not self.enabled:
            return await call_next(request)
        
        # 속도 제한 면제 경로 확인
        if self._is_exempted_path(request.url.path):
            return await call_next(request)
        
        # 파트너 ID 가져오기
        partner_id = get_request_attribute("partner_id")
        if not partner_id:
            # 파트너 ID가 없으면 기본 속도 제한 사용
            return await call_next(request)
        
        # 속도 제한 키 생성 (파트너별 + 엔드포인트별)
        path = request.url.path
        rate_limit_key = f"rate_limit:partner:{partner_id}:{path}"
        
        # 엔드포인트에 대한 제한 가져오기
        limits = self._get_limit_for_endpoint(path)
        limit = limits["limit"]
        window = limits["window"]
        block_time = limits["block_time"]
        
        # 차단 여부 확인
        is_blocked, block_ttl = await self._is_blocked(rate_limit_key)
        if is_blocked:
            # 응답 헤더 설정
            headers = {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + block_ttl),
                "Retry-After": str(block_ttl)
            }
            
            # 차단된 요청 응답
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
        is_limited, count, _, reset_time = await self._is_rate_limited(rate_limit_key, limit, window)
        
        # 응답 헤더 설정
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(max(0, limit - count)),
            "X-RateLimit-Reset": str(reset_time)
        }
        
        # 제한 초과 시 차단
        if is_limited:
            # 차단 시간이 설정된 경우에만 차단
            if block_time > 0:
                await self._block_key(rate_limit_key, block_time)
                headers["Retry-After"] = str(block_time)
            else:
                # 차단하지 않고 다음 윈도우까지 대기 시간 계산
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
        
        # 응답 객체 생성
        response = await call_next(request)
        
        # 응답 헤더에 속도 제한 정보 추가
        for key, value in headers.items():
            response.headers[key] = value
        
        return response
    
    def _is_exempted_path(self, path: str) -> bool:
        """속도 제한 면제 경로 확인"""
        exempted_paths = [
            "/api/health",
            "/docs",
            "/redoc",
            "/openapi.json"
        ]
        return any(path.startswith(exempt_path) for exempt_path in exempted_paths)