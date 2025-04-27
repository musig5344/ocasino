"""
FastAPI 애플리케이션 진입점 (리팩토링됨)
애플리케이션 생성 및 설정을 app 모듈에 위임
"""
import logging
# import uvicorn # 서버 실행은 별도 스크립트나 Docker에서 처리
from fastapi.staticfiles import StaticFiles

from backend.core.config import settings
# from backend.db.database import read_engine, write_engine # Lifespan에서 처리
from backend.api.api import setup_api
# from backend.core.exceptions import AppException # exceptions 모듈에서 처리
# from backend.domain_events import initialize_event_system # 필요 시 lifespan 또는 다른 곳에서 호출

# 새로 추가된 app 모듈 임포트
from backend.app.base import create_app
from backend.app.middlewares import register_middlewares
from backend.app.exceptions import register_exception_handlers
from backend.app.openapi import register_openapi

# 새로운 로깅 설정 함수 임포트
from backend.core.logging import configure_logging

# --- 로깅 설정 --- 
# 기존 logging.basicConfig 제거
# logging.basicConfig(
#     level=settings.LOG_LEVEL,
#     format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
#     handlers=[logging.StreamHandler()]
# )
# logger = logging.getLogger(__name__) # configure_logging에서 루트 로거 설정

# 애플리케이션 생성 전 로깅 설정 적용
configure_logging(
    log_level=settings.LOG_LEVEL,
    json_logs=settings.JSON_LOGS, 
    log_file=settings.LOG_FILE # 설정 파일에 JSON_LOGS와 LOG_FILE 정의 필요
)

logger = logging.getLogger(__name__) # 설정 후 로거 인스턴스 가져오기

# FastAPI 앱 생성 (app.base.create_app 호출)
app = create_app()

# 미들웨어 등록 (app.middlewares.register_middlewares 호출)
register_middlewares(app)

# 전역 예외 핸들러 등록 (app.exceptions.register_exception_handlers 호출)
register_exception_handlers(app)

# 커스텀 OpenAPI 및 Swagger UI 등록 (app.openapi.register_openapi 호출)
register_openapi(app)

# API 라우터 설정 (기존 setup_api 호출 유지)
setup_api(app)

# 정적 파일 마운트 (필요한 경우 유지)
if settings.MOUNT_STATIC_FILES:
    # Ensure the 'static' directory exists at the project root or adjust the path
    # Example assumes 'static' is relative to the project root where main.py is run
    try:
        app.mount("/static", StaticFiles(directory="static"), name="static")
        logger.info("Mounted static files directory.")
    except RuntimeError as e:
        logger.warning(f"Could not mount static files: {e}. Ensure 'static' directory exists.")


# --- 삭제 또는 주석 처리된 기존 코드 ---
# @asynccontextmanager
# async def lifespan(app: FastAPI): ... (app/lifespan.py로 이동)

# async def init_db(): ... (필요 시 lifespan 등에서 관리)

# app = FastAPI(...) (app/base.py로 이동)

# if settings.BACKEND_CORS_ORIGINS: ... (app/base.py로 이동)

# @app.middleware("http") ... (app/middlewares.py로 이동)

# @app.exception_handler(AppException) ... (app/exceptions.py로 이동)
# @app.exception_handler(Exception) ... (app/exceptions.py로 이동)

# app.include_router(api_router, prefix="/api") (setup_api에서 처리)

# @app.on_event("startup") ... (lifespan으로 대체)
# @app.on_event("shutdown") ... (lifespan으로 대체)

# @app.get("/api/health", tags=["Health"]) ... (setup_api 내에서 관리 권장)

# @app.get("/api/docs", include_in_schema=False) ... (app/openapi.py로 이동)

# def custom_openapi(): ... (app/openapi.py로 이동)

# 서버 실행 (주석 처리 또는 삭제)
# if __name__ == "__main__":
#     logger.info(f"Starting server on http://{settings.SERVER_HOST}:{settings.SERVER_PORT}")
#     uvicorn.run(
#         "backend.main:app",
#         host=settings.SERVER_HOST,
#         port=settings.SERVER_PORT,
#         reload=settings.DEBUG, # 개발 환경에서만 reload=True 사용
#         log_level=settings.LOG_LEVEL.lower(),
#         workers=settings.UVICORN_WORKERS
#     )