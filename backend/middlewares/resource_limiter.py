"""
리소스 제한 미들웨어
시스템 안정성을 위한 리소스 사용량 제한
"""
import asyncio
import time
import logging
from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp
from starlette.status import HTTP_429_TOO_MANY_REQUESTS, HTTP_413_REQUEST_ENTITY_TOO_LARGE, HTTP_408_REQUEST_TIMEOUT

# 설정 값 가져오기 (예: backend.core.config.settings)
from backend.core.config import settings

logger = logging.getLogger(__name__)

class ResourceLimiterMiddleware(BaseHTTPMiddleware):
    """
    리소스 제한 미들웨어
    
    동시 요청 수, 요청 본문 크기, 처리 시간 제한 기능 제공
    """
    
    def __init__(
        self, 
        app: ASGIApp, 
        max_concurrent_requests: Optional[int] = None,
        max_request_body_size: Optional[int] = None,  # 바이트 단위
        request_timeout: Optional[float] = None,  # 초 단위
    ):
        super().__init__(app)
        # 설정 파일 또는 환경 변수에서 값 로드, 없으면 기본값 사용
        self.max_concurrent_requests = max_concurrent_requests or getattr(settings, 'MAX_CONCURRENT_REQUESTS', 100)
        self.max_request_body_size = max_request_body_size or getattr(settings, 'MAX_REQUEST_BODY_SIZE', 10 * 1024 * 1024) # 10MB
        self.request_timeout = request_timeout or getattr(settings, 'REQUEST_TIMEOUT_SECONDS', 30.0) # 30초
        
        # 동시성 제어를 위한 세마포어 초기화
        self.semaphore = asyncio.Semaphore(self.max_concurrent_requests)
        self.active_requests = 0 # 현재 활성 요청 수 (모니터링용)
        
        logger.info(f"ResourceLimiterMiddleware initialized: Max Concurrent={self.max_concurrent_requests}, Max Body Size={self.max_request_body_size} bytes, Timeout={self.request_timeout}s")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 요청 본문 크기 제한 확인 (스트리밍 요청은 제외하거나 다른 방식 필요)
        content_length_str = request.headers.get("content-length")
        if content_length_str:
            try:
                content_length = int(content_length_str)
                if content_length > self.max_request_body_size:
                    logger.warning(
                        f"Request body size limit exceeded: {content_length} bytes > {self.max_request_body_size} bytes "
                        f"for {request.method} {request.url.path}"
                    )
                    return Response(
                        content=f"Request body too large. Maximum size allowed is {self.max_request_body_size} bytes.",
                        status_code=HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        media_type="text/plain"
                    )
            except ValueError:
                logger.warning(f"Invalid content-length header: {content_length_str}")
                # 유효하지 않은 헤더 처리 (예: 거부 또는 무시)
                return Response("Invalid Content-Length header", status_code=400, media_type="text/plain")

        # 동시 요청 제한 확인 (세마포어 획득 시도)
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=0.1) # 즉시 획득 못하면 타임아웃 (선택적)
        except asyncio.TimeoutError:
             logger.warning(
                 f"Concurrency limit reached. Rejecting request. "
                 f"Active: {self.active_requests}, Max: {self.max_concurrent_requests}"
             )
             return Response(
                 content="Too many concurrent requests. Please try again later.",
                 status_code=HTTP_429_TOO_MANY_REQUESTS,
                 media_type="text/plain"
             )

        # 세마포어 획득 성공 -> 활성 요청 수 증가
        self.active_requests += 1
        start_time = time.perf_counter()
        response = None
        
        try:
            # 요청 처리 시간 제한 적용
            response = await asyncio.wait_for(
                call_next(request),
                timeout=self.request_timeout
            )
            process_time = time.perf_counter() - start_time
            # 성공 로그 (필요시)
            # logger.debug(f"Request processed successfully in {process_time:.4f}s")
            return response
            
        except asyncio.TimeoutError:
            process_time = time.perf_counter() - start_time
            logger.warning(
                f"Request processing timeout: {request.method} {request.url.path} exceeded {self.request_timeout}s. "
                f"Processing time: {process_time:.4f}s"
            )
            # 타임아웃 발생 시 408 응답 반환
            return Response(
                content=f"Request timed out after {self.request_timeout} seconds.",
                status_code=HTTP_408_REQUEST_TIMEOUT,
                media_type="text/plain"
            )
        except Exception as e:
             # 예기치 않은 오류 발생 시 로그 기록 및 500 에러 반환
             process_time = time.perf_counter() - start_time
             logger.error(
                 f"Unhandled exception during request processing: {e} for {request.method} {request.url.path}. "
                 f"Processing time: {process_time:.4f}s",
                 exc_info=True
             )
             # FastAPI의 기본 예외 처리기로 전달하기 위해 예외를 다시 발생시킬 수도 있음
             # raise e 
             # 또는 직접 500 에러 응답 생성
             return Response("Internal Server Error", status_code=500, media_type="text/plain")
             
        finally:
            # 요청 처리 완료 후 세마포어 해제 및 활성 요청 수 감소
            self.semaphore.release()
            self.active_requests -= 1 