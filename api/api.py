from fastapi import APIRouter, FastAPI, Depends, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
import logging

from backend.api.routers import auth, partners, games, wallet, reports
from backend.api.errors.handlers import register_exception_handlers
from backend.core.config import settings
from backend.middlewares.ip_whitelist import IPWhitelistMiddleware
from backend.middlewares.request_validation import RequestValidationMiddleware
from backend.middlewares.audit_log import AuditLogMiddleware

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
    
    # 보안 미들웨어 추가
    app.add_middleware(IPWhitelistMiddleware)
    app.add_middleware(RequestValidationMiddleware)
    app.add_middleware(AuditLogMiddleware)
    
    # 예외 핸들러 등록
    register_exception_handlers(app)
    
    # API 라우터 등록
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    
    # API 상태 확인 엔드포인트
    @app.get("/api/health", tags=["Health"])
    def health_check():
        """API 상태 확인 엔드포인트"""
        return {"status": "ok"}
    
    # 요청 로깅 미들웨어
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """요청 로깅 미들웨어"""
        # 요청 처리
        response = await call_next(request)
        
        # 상태 확인 요청은 로깅에서 제외
        if not request.url.path.startswith("/api/health"):
            logger.info(f"{request.method} {request.url.path} -> {response.status_code}")
        
        return response