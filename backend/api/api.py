from fastapi import APIRouter, FastAPI, Depends, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
import logging

# auth, wallet, reports, health 임포트 제거
# from backend.api.routers import health # 제거
# 주석 처리: 관리자 라우터 임포트
# from backend.api.routers.admin import partners as admin_partners, users as admin_users
from backend.api.errors.handlers import register_exception_handlers
from backend.core.config import settings
from backend.middlewares.auth_middleware import AuthMiddleware
from backend.middlewares.ip_whitelist import IPWhitelistMiddleware
from backend.middlewares.error_handling_middleware import ErrorHandlingMiddleware
from backend.middlewares.rate_limit_middleware import RateLimitMiddleware
from backend.middlewares.request_validation import RequestValidationMiddleware
from backend.middlewares.audit_log import AuditLogMiddleware
from backend.middlewares.tracing import TracingMiddleware
# 주석 처리 또는 제거: request_context_middleware 임포트
# from backend.utils.request_context import request_context_middleware
from backend.partners import api as partners_api
from backend.games import api as games_api
from backend.wallet import api as wallet_api
from backend.auth import api as auth_api
from backend.reports import api as reports_api
from backend.health import api as health_api # 새로운 health API 임포트

logger = logging.getLogger(__name__)

# API 라우터 초기화
api_router = APIRouter()

# 각 라우터 등록
api_router.include_router(auth_api.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(partners_api.router, prefix="/partners", tags=["Partner Management"])
api_router.include_router(games_api.router, prefix="/games", tags=["Game Integration"])
api_router.include_router(wallet_api.router, prefix="/wallet", tags=["Wallet"])
api_router.include_router(reports_api.router, prefix="/reports", tags=["Reporting"])
# health_api.router 사용
api_router.include_router(health_api.router, prefix="/health", tags=["Health & Diagnostics"])

# 주석 처리: 관리자 라우터 포함
# admin_router = APIRouter()
# admin_router.include_router(admin_partners.router, prefix="/partners", tags=["Admin - Partners"])
# admin_router.include_router(admin_users.router, prefix="/users", tags=["Admin - Users"])
# 
# api_router.include_router(admin_router, prefix="/admin")

def setup_api(app: FastAPI) -> None:
    """API 설정 및 등록 함수"""
    
    # CORS 미들웨어 설정
    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    
    # 미들웨어 등록 (순서 중요)
    # 주석 처리: request_context_middleware 사용 부분
    # app.middleware("http")(request_context_middleware)      # 요청 컨텍스트 초기화
    app.add_middleware(ErrorHandlingMiddleware)       # 오류 처리 다시 활성화
    # app.add_middleware(AuditLogMiddleware)            # 감사 로깅 임시 주석 처리 (문제 원인)
    app.add_middleware(RateLimitMiddleware)           # 속도 제한 다시 활성화
    app.add_middleware(AuthMiddleware)                # 인증 다시 활성화
    
    # 예외 핸들러 등록
    register_exception_handlers(app)
    
    # API 라우터 등록
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)