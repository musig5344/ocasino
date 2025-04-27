from starlette.background import BackgroundTasks
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
import logging
import time
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from fastapi import Request, Response, Depends
from starlette.types import ASGIApp
import traceback
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.services.audit.audit_service import AuditLogService
from backend.db.database import write_session_factory, get_write_db
from backend.models.domain.audit_log import AuditLog, AuditLogLevel, AuditLogType
from backend.utils.request_context import set_request_context, clear_request_context, get_request_context

logger = logging.getLogger(__name__)

async def save_audit_log_task(
    request_id: str,
    method: str,
    path: str,
    client_ip: str,
    api_key: Optional[str],
    status_code: int,
    process_time: float,
    request_body: Optional[Any] = None,
    response_body: Optional[Any] = None,
    error: Optional[str] = None
) -> None:
    """감사 로그를 데이터베이스에 저장하는 백그라운드 작업"""
    session: Optional[AsyncSession] = None
    try:
        session = write_session_factory()
        async with session:
            # 여기에 파트너 ID와 API 키 ID를 가져오는 로직 추가 필요 (예: api_key를 기반으로 DB 조회)
            partner_id = None
            api_key_id = None
            
            log_data = AuditLog(
                id=uuid.UUID(request_id),
                timestamp=datetime.utcnow(),
                level=AuditLogLevel.ERROR if error else AuditLogLevel.INFO,
                log_type=AuditLogType.API_ACCESS,
                action=f"{method} {path}",
                description=f"API request processed: {method} {path}",
                resource_type="api_endpoint",
                resource_id=path,
                partner_id=partner_id, # 실제 값으로 채워야 함
                api_key_id=api_key_id, # 실제 값으로 채워야 함
                ip_address=client_ip,
                request_id=request_id,
                request_path=path,
                request_method=method,
                status_code=str(status_code),
                response_time_ms=int(process_time * 1000),
                log_metadata=json.dumps({
                    "request_body": request_body,
                    "response_body": response_body,
                    "error": error
                })
            )
            session.add(log_data)
            await session.commit()
    except Exception as e:
        logger.error(f"Background task failed to save audit log: {e}", exc_info=True)
        if session:
            await session.rollback()
    finally:
        if session:
            await session.close()

class AuditLogMiddleware(BaseHTTPMiddleware):
    """
    감사 로깅 미들웨어
    
    API 요청에 대한 감사 로그를 생성합니다.
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.exclude_paths = settings.AUDIT_LOG_EXCLUDE_PATHS
        
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """
        미들웨어 분배 함수
        
        Args:
            request: 요청 객체
            call_next: 다음 미들웨어 호출 함수
            
        Returns:
            응답 객체
        """
        # 감사 로깅 예외 경로 확인
        if self._is_exempted_path(request.url.path):
            return await call_next(request)
        
        # 요청 시작 시간
        start_time = time.time()
        
        # 고유 요청 ID 생성
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # 로그 정보 수집
        method = request.method
        path = request.url.path
        client_ip = self._get_client_ip(request)
        api_key = request.headers.get("X-API-Key")
        
        # 요청 본문 복제
        try:
            body_bytes = await request.body()
            # 원본 요청 본문을 복원하여 다음 미들웨어에서 사용할 수 있도록 함
            async def receive():
                return {"type": "http.request", "body": body_bytes}
            
            request._receive = receive
            
            # 요청 본문 파싱 (JSON인 경우)
            body_content = None
            content_type = request.headers.get("Content-Type", "")
            if "application/json" in content_type and body_bytes:
                try:
                    body_content = json.loads(body_bytes.decode("utf-8"))
                    # 민감 정보 마스킹
                    body_content = self._mask_sensitive_data(body_content)
                except:
                    body_content = "(invalid JSON)"
        except:
            body_content = None
        
        # 응답 처리
        try:
            response = await call_next(request)
            
            # 응답 상태 코드
            status_code = response.status_code
            
            # 처리 시간 계산
            process_time = time.time() - start_time
            
            # 응답 본문 복제
            response_body = None
            if settings.AUDIT_LOG_INCLUDE_RESPONSE_BODY:
                try:
                    response_body = await self._get_response_body(response)
                    # 원본 응답 본문 복원
                    await self._restore_response_body(response, response_body)
                except:
                    response_body = None
            
            # 백그라운드 작업 설정
            if not hasattr(response, 'background') or response.background is None:
                 response.background = BackgroundTasks()

            response.background.add_task(
                save_audit_log_task,
                request_id=request_id,
                method=method,
                path=path,
                client_ip=client_ip,
                api_key=api_key,
                status_code=status_code,
                process_time=process_time,
                request_body=body_content,
                response_body=response_body,
                error=None
            )
            return response
        except Exception as e:
            # 오류 발생 시 로깅
            status_code = 500
            process_time = time.time() - start_time
            
            # 감사 로그 생성
            await self._create_audit_log(
                request_id=request_id,
                method=method,
                path=path,
                client_ip=client_ip,
                api_key=api_key,
                status_code=status_code,
                process_time=process_time,
                request_body=body_content,
                response_body=None,
                error=str(e)
            )
            
            # 오류 전파
            raise
    
    def _is_exempted_path(self, path: str) -> bool:
        """
        감사 로깅 예외 경로 확인
        
        Args:
            path: 요청 경로
            
        Returns:
            bool: 예외 여부
        """
        # 감사 로깅 예외 경로 목록
        exempted_paths = [
            "/api/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/static/"
        ]
        
        return any(path.startswith(exempt_path) for exempt_path in exempted_paths)
    
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
    
    def _mask_sensitive_data(self, data: Any) -> Any:
        """
        민감 정보 마스킹
        
        Args:
            data: 마스킹할 데이터
            
        Returns:
            Any: 마스킹된 데이터
        """
        if isinstance(data, dict):
            # 민감 필드 목록
            sensitive_fields = [
                "password", "api_key", "secret", "token", "authorization",
                "credit_card", "ssn", "social_security", "private_key",
                "access_token", "refresh_token", "secure", "auth",
                "user_password", "client_secret" # 추가 민감 필드 예시
            ]
            
            # 딕셔너리 복사
            masked_data = {}
            
            for key, value in data.items():
                # 키가 민감 필드인지 확인
                lower_key = key.lower()
                if any(sensitive in lower_key for sensitive in sensitive_fields):
                    # 길이에 따라 마스킹
                    if isinstance(value, str):
                        if len(value) > 6:
                            masked_data[key] = value[:3] + "***" + value[-3:]
                        else:
                            masked_data[key] = "******"
                    else:
                        masked_data[key] = "******"
                else:
                    # 재귀적으로 마스킹
                    masked_data[key] = self._mask_sensitive_data(value)
            
            return masked_data
        elif isinstance(data, list):
            # 리스트 각 항목 재귀적으로 마스킹
            return [self._mask_sensitive_data(item) for item in data]
        else:
            # 기본 타입은 그대로 반환
            return data
    
    async def _get_response_body(self, response: Response) -> Optional[Dict[str, Any]]:
        """
        응답 본문 가져오기
        
        Args:
            response: 응답 객체
            
        Returns:
            Optional[Dict[str, Any]]: 응답 본문
        """
        if not hasattr(response, "body"):
            return None
        
        body = response.body
        if not body:
            return None
        
        # JSON 파싱 시도
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                return json.loads(body.decode("utf-8"))
            except:
                return None
        
        return None
    
    async def _restore_response_body(self, response: Response, body: Any) -> None:
        """
        응답 본문 복원
        
        Args:
            response: 응답 객체
            body: 복원할 본문
        """
        # 본문 복원 로직 (필요한 경우 구현)
        pass
    
    async def _create_audit_log(
        self,
        request_id: str,
        method: str,
        path: str,
        client_ip: str,
        api_key: Optional[str],
        status_code: int,
        process_time: float,
        request_body: Optional[Any] = None,
        response_body: Optional[Any] = None,
        error: Optional[str] = None
    ) -> None:
        """
        감사 로그 생성
        
        Args:
            request_id: 요청 ID
            method: HTTP 메소드
            path: 요청 경로
            client_ip: 클라이언트 IP
            api_key: API 키
            status_code: 응답 상태 코드
            process_time: 처리 시간 (초)
            request_body: 요청 본문
            response_body: 응답 본문
            error: 오류 메시지
        """
        session: Optional[AsyncSession] = None # 세션 변수 초기화
        try:
            # 세션 팩토리 호출하여 세션 얻기
            session = write_session_factory()
            # 얻은 세션을 async with와 함께 사용
            async with session: # 세션 객체로 컨텍스트 관리
                # 세션 내에서 트랜잭션 시작 (선택 사항, 서비스 내에서 처리할 수도 있음)
                # async with session.begin():
                audit_service = AuditLogService(session)
                # 로그 데이터 생성
                log_data = AuditLog(
                    id=uuid.UUID(request_id),
                    timestamp=datetime.utcnow(),
                    level=AuditLogLevel.ERROR if error else AuditLogLevel.INFO,
                    log_type=AuditLogType.API_ACCESS,
                    action=f"{{method}} {{path}}",
                    description=f"API request processed: {{method}} {{path}}",
                    resource_type="api_endpoint",
                    resource_id=path,
                    partner_id=None,
                    api_key_id=None,
                    ip_address=client_ip,
                    request_id=request_id,
                    request_path=path,
                    request_method=method,
                    status_code=str(status_code),
                    response_time_ms=int(process_time * 1000),
                    log_metadata=json.dumps({
                        "request_body": request_body,
                        "response_body": response_body,
                        "error": error
                    })
                )
                # Audit Service 사용 또는 직접 추가
                # await audit_service.create_audit_log(log_data)
                session.add(log_data) # 직접 추가 예시
                await session.commit() # 미들웨어 레벨에서 커밋

        except Exception as e:
            logger.error(f"Failed to create audit log: {{e}}", exc_info=True)
            if session:
                 await session.rollback() # 오류 시 롤백
        finally:
            # 세션 닫기 (중요)
            if session:
                await session.close()