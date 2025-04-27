from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from typing import Optional, Dict, Any
import logging
import json
import time
import re

from backend.core.config import settings
from backend.core.security import compute_hmac, verify_hmac

logger = logging.getLogger(__name__)

class RequestValidationMiddleware(BaseHTTPMiddleware):
    """
    요청 유효성 검사 미들웨어
    
    요청의 무결성과 타임스탬프를 검증합니다.
    """
    
    async def dispatch(self, request: Request, call_next):
        """
        미들웨어 분배 함수
        
        Args:
            request: 요청 객체
            call_next: 다음 미들웨어 호출 함수
            
        Returns:
            응답 객체
        """
        # 유효성 검사 예외 경로 확인
        if self._is_exempted_path(request.url.path):
            return await call_next(request)
        
        # 요청 본문 검증 (POST, PUT, PATCH 요청만)
        if request.method in ["POST", "PUT", "PATCH"]:
            # 요청 본문을 읽기 위해 복제
            body_bytes = await request.body()
            
            # 원본 요청 본문을 복원하여 다음 미들웨어에서 사용할 수 있도록 함
            async def receive():
                return {"type": "http.request", "body": body_bytes}
            
            request._receive = receive
            
            # 본문 검증
            validation_result = await self._validate_request_body(request, body_bytes)
            if validation_result:
                # 유효성 검사 실패
                return validation_result
        
        # 타임스탬프 검증
        timestamp_validation = self._validate_timestamp(request)
        if timestamp_validation:
            return timestamp_validation
        
        # API 키가 있는 경우 HMAC 서명 검증
        api_key = request.headers.get("X-API-Key")
        if api_key and settings.ENABLE_API_HMAC:
            hmac_validation = await self._validate_hmac(request, body_bytes if request.method in ["POST", "PUT", "PATCH"] else None)
            if hmac_validation:
                return hmac_validation
        
        # 유효성 검사 통과
        return await call_next(request)
    
    def _is_exempted_path(self, path: str) -> bool:
        """
        유효성 검사 예외 경로 확인
        
        Args:
            path: 요청 경로
            
        Returns:
            bool: 예외 여부
        """
        # 유효성 검사 예외 경로 목록
        exempted_paths = [
            "/api/health",
            "/docs",
            "/redoc",
            "/openapi.json"
        ]
        
        return any(path.startswith(exempt_path) for exempt_path in exempted_paths)
    
    async def _validate_request_body(self, request: Request, body_bytes: bytes) -> Optional[JSONResponse]:
        """
        요청 본문 유효성 검사
        
        Args:
            request: 요청 객체
            body_bytes: 요청 본문 바이트
            
        Returns:
            Optional[JSONResponse]: 오류 응답 또는 None
        """
        # 본문이 비어있는 경우 건너뛰기
        if not body_bytes:
            return None
        
        # JSON 검증
        content_type = request.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                # JSON 파싱
                json.loads(body_bytes.decode("utf-8"))
            except json.JSONDecodeError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "code": "INVALID_REQUEST",
                            "message": "Invalid JSON in request body"
                        }
                    }
                )
        
        # SQL 인젝션 검사
        body_str = body_bytes.decode("utf-8")
        if self._contains_sql_injection_attempts(body_str):
            logger.warning(f"SQL injection attempt detected in request to {request.url.path}")
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "Potentially malicious content detected in request"
                    }
                }
            )
        
        return None
    
    def _validate_timestamp(self, request: Request) -> Optional[JSONResponse]:
        """
        요청 타임스탬프 유효성 검사
        
        Args:
            request: 요청 객체
            
        Returns:
            Optional[JSONResponse]: 오류 응답 또는 None
        """
        # 타임스탬프 검증이 비활성화된 경우 건너뛰기
        if not settings.ENABLE_TIMESTAMP_VALIDATION:
            return None
        
        # X-Timestamp 헤더 확인
        timestamp_str = request.headers.get("X-Timestamp")
        if not timestamp_str:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "Missing X-Timestamp header"
                    }
                }
            )
        
        try:
            # 타임스탬프 파싱
            timestamp = int(timestamp_str)
            current_time = int(time.time())
            
            # 타임스탬프 유효성 검사 (5분 이내)
            time_diff = abs(current_time - timestamp)
            if time_diff > settings.TIMESTAMP_MAX_DIFF:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "code": "INVALID_TIMESTAMP",
                            "message": "Request timestamp is too old or in the future"
                        }
                    }
                )
            
            return None
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "Invalid X-Timestamp format"
                    }
                }
            )
    
    async def _validate_hmac(self, request: Request, body_bytes: Optional[bytes] = None) -> Optional[JSONResponse]:
        """
        HMAC 서명 유효성 검사
        
        Args:
            request: 요청 객체
            body_bytes: 요청 본문 바이트
            
        Returns:
            Optional[JSONResponse]: 오류 응답 또는 None
        """
        # X-Signature 헤더 확인
        signature = request.headers.get("X-Signature")
        if not signature:
            return None  # 서명이 없으면 검증하지 않음
        
        # API 키 가져오기
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "API key is required for signature validation"
                    }
                }
            )
        
        # 타임스탬프 가져오기
        timestamp = request.headers.get("X-Timestamp")
        if not timestamp:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "Timestamp is required for signature validation"
                    }
                }
            )
        
        # 서명 검증에 필요한 요소 구성
        path = request.url.path
        query_string = request.url.query.decode("utf-8") if hasattr(request.url.query, "decode") else str(request.url.query)
        
        # 서명 검증
        is_valid = await verify_hmac(
            api_key=api_key,
            signature=signature,
            method=request.method,
            path=path,
            query_string=query_string,
            timestamp=timestamp,
            body=body_bytes
        )
        
        if not is_valid:
            logger.warning(f"Invalid HMAC signature for API key {api_key[:5]}...")
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "INVALID_SIGNATURE",
                        "message": "Invalid signature"
                    }
                }
            )
        
        return None
    
    def _contains_sql_injection_attempts(self, content: str) -> bool:
        """
        SQL 인젝션 시도 감지
        
        Args:
            content: 검사할 내용
            
        Returns:
            bool: SQL 인젝션 시도 여부
        """
        # SQL 인젝션 패턴
        sql_patterns = [
            r"(?i)\bSELECT\b.+\bFROM\b",
            r"(?i)\bINSERT\b.+\bINTO\b",
            r"(?i)\bUPDATE\b.+\bSET\b",
            r"(?i)\bDELETE\b.+\bFROM\b",
            r"(?i)\bDROP\b.+\bTABLE\b",
            r"(?i)\bUNION\b.+\bSELECT\b",
            r"(?i)\bEXEC\b.*\bsp_\w+\b",
            r"(?i)(--).*$",
            r"(?i)\/\*.*\*\/",
            r"(?i)'.*--",
            r"(?i)'.*#",
            r"(?i)'.*\/\*",
            r"(?i)';.*--",
            r"(?i)';.*#"
        ]
        
        # 패턴 검사
        for pattern in sql_patterns:
            if re.search(pattern, content):
                return True
        
        return False