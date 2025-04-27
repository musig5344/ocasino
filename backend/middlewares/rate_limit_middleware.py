from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from starlette.responses import Response
from typing import Dict, Optional, Callable, Union
import time
import logging
from datetime import datetime
from backend.core.config import settings
from backend.utils.request_context import get_request_attribute
from backend.cache.redis_cache import get_redis_client
from backend.core.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    요청 속도 제한 미들웨어
    
    파트너 및 엔드포인트별로 API 요청 속도를 제한합니다.
    """
    
    def __init__(self, app: ASGIApp):
        """미들웨어 초기화"""
        super().__init__(app)
        self.enabled = settings.ENABLE_RATE_LIMITING
        self.strategy = settings.RATE_LIMIT_STRATEGY
        
        # 엔드포인트별 속도 제한 설정
        self.endpoint_limits = self._load_endpoint_limits()
        self.limiter: Optional[RateLimiter] = None
    
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
        count = await self.limiter.redis.incr(window_key)
        
        # 첫 번째 요청인 경우 만료 시간 설정
        if count == 1:
            await self.limiter.redis.expire(window_key, window)
        
        # TTL 확인
        ttl = await self.limiter.redis.ttl(window_key)
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
        ttl = await self.limiter.redis.ttl(block_key)
        
        return ttl > 0, ttl
    
    async def _block_key(self, key: str, block_time: int) -> None:
        """키 차단"""
        if block_time <= 0 or not self.limiter or not hasattr(self.limiter, 'redis'):
            return
        
        # 차단 키
        block_key = f"{key}:blocked"
        
        # 차단 설정
        await self.limiter.redis.set(block_key, 1, ex=block_time)
    
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """미들웨어 처리 로직"""
        if not self.enabled:
            return await call_next(request)
        
        # Limiter 인스턴스 생성 (매 요청마다 생성 - 비효율적, 개선 필요)
        if self.limiter is None: # 인스턴스가 없을 때만 생성 시도
            try:
                redis_client = await get_redis_client()
                if not redis_client:
                    logger.error("Failed to get Redis client for rate limiting. Skipping check.")
                    return await call_next(request)
                self.limiter = RateLimiter(redis_client=redis_client) # RateLimiter 초기화
                logger.info(f"RateLimiter initialized in dispatch for request {request.url.path}")
            except Exception as e:
                logger.error(f"Failed to initialize RateLimiter in dispatch: {e}")
                # Limiter 초기화 실패 시에도 요청 처리 계속 (정책에 따라 변경 가능)
                return await call_next(request)

        identifier = self._get_identifier(request)
        if not identifier:
            logger.warning("Could not determine identifier for rate limiting. Skipping check.")
            return await call_next(request)

        path = request.url.path
        
        # 면제 경로 확인
        if self._is_exempted_path(path):
            return await call_next(request)

        try:
            # RateLimiter의 check 메서드 호출 (이 메서드가 없으면 직접 로직 구현)
            if hasattr(self.limiter, 'check'):
                await self.limiter.check(identifier, path)
            else:
                # RateLimiter.check가 없다면, _is_rate_limited 등을 직접 호출하는 로직 구현
                limit_info = self._get_limit_for_endpoint(path)
                limit = limit_info['limit']
                window = limit_info['window']
                block_time = limit_info.get('block_time', 0)

                is_blocked, block_ttl = await self._is_blocked(identifier)
                if is_blocked:
                    logger.warning(f"Identifier {identifier} is blocked for {block_ttl} seconds.")
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Blocked due to previous rate limit exceeding. Try again in {block_ttl} seconds."
                    )

                is_limited, count, limit, reset_time = await self._is_rate_limited(identifier, limit, window)
                if is_limited:
                    logger.warning(f"Rate limit exceeded for identifier: {identifier}, path: {path}. Count: {count}/{limit}")
                    await self._block_key(identifier, block_time)
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Rate limit exceeded. Limit: {limit} requests per {window} seconds. Try again after {datetime.fromtimestamp(reset_time).isoformat()}",
                        headers={"Retry-After": str(reset_time - int(time.time()))}
                    )

            # 요청 처리
            response = await call_next(request)
            return response
            
        except HTTPException as http_exc:
            # RateLimiter에서 발생시킨 HTTPException 처리 (예: 429)
            if http_exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                 logger.warning(f"Rate limit exceeded for identifier: {identifier}, path: {path}")
            else:
                 logger.error(f"HTTPException during rate limiting check: {http_exc.detail}", exc_info=False)
            raise http_exc # 예외를 다시 발생시켜 FastAPI가 처리하도록 함
            
        except Exception as e:
            logger.error(f"Error during rate limiting check: {e}", exc_info=True)
            # 오류 발생 시 요청 처리 계속 또는 500 에러 반환 선택
            # return JSONResponse(status_code=500, content={"detail": "Internal server error during rate limit check."})
            return await call_next(request) # 또는 500 에러 반환
    
    def _is_exempted_path(self, path: str) -> bool:
        """속도 제한 면제 경로 확인"""
        exempted_paths = [
            "/api/health",
            "/docs",
            "/redoc",
            "/openapi.json"
        ]
        return any(path.startswith(exempt_path) for exempt_path in exempted_paths)

    # 요청 식별자 생성 메서드 (예시)
    def _get_identifier(self, request: Request) -> Optional[str]:
        # 파트너 ID 또는 클라이언트 IP 기반 식별자 생성 로직
        # 예: API 키 기반 파트너 ID 추출 또는 IP 주소 사용
        # 이 부분은 실제 인증/파트너 정보 접근 방식에 따라 구현 필요
        # partner_id = request.state.partner_id # 예시: 인증 미들웨어에서 설정
        partner_id = request.headers.get("X-Partner-ID") # 임시로 헤더 사용
        if partner_id:
            return f"partner:{partner_id}"
        # Fallback to IP address if no partner info
        ip = self._get_client_ip(request)
        if ip:
            return f"ip:{ip}"
        return None

    def _get_client_ip(self, request: Request) -> str:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "unknown"