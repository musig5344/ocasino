"""
FastAPI 애플리케이션 진입점
애플리케이션 설정 및 시작
"""
import logging
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import uuid

from backend.api.api import api_router
from backend.core.config import settings
from backend.core.exceptions import BaseAPIException
from backend.db.database import Base, engine
from backend.domain_events import initialize_event_system
from backend.services.auth.auth_service import AuthService
from backend.db.database import get_db

# 로깅 설정
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    version=settings.PROJECT_VERSION,
    docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/api/redoc" if settings.ENVIRONMENT != "production" else None,
    openapi_url="/api/openapi.json" if settings.ENVIRONMENT != "production" else None
)

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 요청 ID 미들웨어
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# 예외 처리기
@app.exception_handler(BaseAPIException)
async def api_exception_handler(request: Request, exc: BaseAPIException):
    """API 예외 처리기"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "request_id": getattr(request.state, "request_id", None)
        }
    )

# API 라우터 등록
app.include_router(api_router, prefix="/api")

# 정적 파일 마운트 (필요한 경우)
if settings.MOUNT_STATIC_FILES:
    app.mount("/static", StaticFiles(directory="static"), name="static")

# 시작 이벤트 핸들러
@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 실행"""
    logger.info(f"Starting {settings.PROJECT_NAME} v{settings.PROJECT_VERSION}")
    
    # 이벤트 시스템 초기화
    initialize_event_system()
    
    # 데이터베이스 연결 테스트
    try:
        async with engine.begin() as conn:
            # 테이블 생성 (개발 환경에서만)
            if settings.ENVIRONMENT == "development" and settings.CREATE_TABLES:
                await conn.run_sync(Base.metadata.create_all)
            
            logger.info("Database connection established")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise

# 종료 이벤트 핸들러
@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 실행"""
    logger.info(f"Shutting down {settings.PROJECT_NAME}")
    
    # 엔진 종료
    if engine:
        await engine.dispose()
        logger.info("Database connection closed")

# 헬스 체크 엔드포인트
@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy", "version": settings.PROJECT_VERSION}

# 직접 실행 시
if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.DEBUG
    )