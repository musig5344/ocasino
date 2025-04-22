from fastapi import APIRouter, FastAPI, Depends, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
import logging

from backend.api.routers import auth, partners, games, wallet, reports
from backend.api.errors.handlers import register_exception_handlers
from backend.core.config import settings
from backend.middlewares.auth_middleware import AuthMiddleware
from backend.middlewares.rate_limit_middleware import RateLimitMiddleware
from backend.middlewares.audit_log_middleware import AuditLogMiddleware
from backend.middlewares.error_handling_middleware import ErrorHandlingMiddleware
from backend.utils.request_context import request_context_middleware

logger = logging.getLogger(__name__)

# API 라우터 초기화
api_router = APIRouter()

# 각 라우터 등록
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(partners.router, prefix="/partners", tags=["Partner Management"])
api_router.include_router(games.router, prefix="/games", tags=["Game Integration"])
api_router.include_router(wallet.router, prefix="/wallet", tags=["Wallet"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reporting"])

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
    app.middleware("http")(request_context_middleware)      # 요청 컨텍스트 초기화
    app.middleware("http")(ErrorHandlingMiddleware())       # 오류 처리 (가장 바깥쪽)
    app.middleware("http")(AuditLogMiddleware())            # 감사 로깅
    app.middleware("http")(RateLimitMiddleware())           # 속도 제한
    app.middleware("http")(AuthMiddleware())                # 인증 (가장 안쪽)
    
    # 예외 핸들러 등록
    register_exception_handlers(app)
    
    # API 라우터 등록
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    
    # API 상태 확인 엔드포인트
    @app.get("/api/health", tags=["Health"])
    def health_check():
        """API 상태 확인 엔드포인트"""
        return {"status": "ok", "version": settings.VERSION}