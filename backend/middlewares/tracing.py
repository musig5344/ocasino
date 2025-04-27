"""
분산 추적 미들웨어
서비스 호출 추적 및 성능 모니터링
"""
import time
import logging
import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

class TracingMiddleware(BaseHTTPMiddleware):
    """
    분산 추적 미들웨어
    
    요청 추적 및 성능 데이터 수집
    """
    
    def __init__(self, app: ASGIApp, trace_header: str = "X-Trace-ID"):
        super().__init__(app)
        self.trace_header = trace_header
    
    async def dispatch(self, request: Request, call_next):
        # 추적 ID 생성 또는 가져오기
        trace_id = request.headers.get(self.trace_header)
        if not trace_id:
            trace_id = str(uuid.uuid4())
        
        # 컨텍스트 변수 등을 사용하여 추적 ID 전파 (필요시)
        # 예를 들어, request.state에 저장하여 API 핸들러에서 접근 가능하게 함
        request.state.trace_id = trace_id
        
        # 시작 시간 기록
        start_time = time.perf_counter() # time.time() 대신 time.perf_counter() 사용 권장
        
        # 요청 정보 로깅 (Extra에 trace_id 포함)
        logger.info(
            f"Request started",
            extra={"trace_id": trace_id, "method": request.method, "path": request.url.path}
        )
        
        response = None
        try:
            response = await call_next(request)
            
            # 처리 시간 계산
            process_time = time.perf_counter() - start_time
            
            # 응답 정보 로깅 (Extra에 trace_id 및 처리 시간 포함)
            logger.info(
                f"Request completed",
                extra={
                    "trace_id": trace_id, 
                    "method": request.method, 
                    "path": request.url.path,
                    "status_code": response.status_code if response else None,
                    "process_time_ms": round(process_time * 1000, 2)
                }
            )
            
            # 추적 ID 응답 헤더에 추가
            if response:
                response.headers[self.trace_header] = trace_id
                # 처리 시간 응답 헤더에 추가 (밀리초 단위)
                response.headers["X-Process-Time-Ms"] = str(round(process_time * 1000, 2))
            
            return response
        except Exception as e:
            # 오류 로깅 (Extra에 trace_id 포함)
            process_time = time.perf_counter() - start_time
            logger.error(
                f"Request failed: {str(e)}",
                exc_info=True,
                extra={
                    "trace_id": trace_id, 
                    "method": request.method, 
                    "path": request.url.path,
                    "process_time_ms": round(process_time * 1000, 2)
                    }
            )
            # 예외를 다시 발생시켜 FastAPI의 기본 예외 처리기가 처리하도록 함
            raise e 