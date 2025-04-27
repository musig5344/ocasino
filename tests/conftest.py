# tests/conftest.py
import sys
import os
from pathlib import Path
import base64 # base64 임포트 추가
from fastapi import FastAPI
# from backend.main import create_app # create_app 임포트 제거
from backend.main import app as main_app # app 인스턴스 직접 임포트 활성화
# from backend.main import app as main_app # app 인스턴스 직접 임포트 (이름 충돌 방지) - 주석 처리
from backend.core.config import Settings, get_settings # Settings 임포트 추가
import backend.core.config as config_module # 모듈 자체를 임포트 (여전히 필요할 수 있음)
# MultiHostUrl 임포트 추가
from pydantic_core import MultiHostUrl

# 프로젝트 루트 디렉토리를 sys.path에 추가
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

import pytest
import asyncio
from typing import Dict, Any, Generator, AsyncGenerator, Tuple
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
# TestClient 주석 처리 또는 제거
# from fastapi.testclient import TestClient
from httpx import AsyncClient # AsyncClient 임포트
from fastapi.testclient import TestClient
from backend.core.dependencies import get_db  # 변경: get_db 경로 수정
from backend.api.dependencies.db import get_read_session, get_write_session, get_sessions  # 유지: 나머지 DB 관련 의존성 경로
from backend.cache.redis_cache import get_redis_client, _redis_client # _redis_client 추가 for reset
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import UUID
from backend.middlewares.auth_middleware import AuthMiddleware
import contextlib
from backend.core.dependencies import get_current_partner_id # 경로 수정
from backend.services.wallet.wallet_service import WalletService
from backend.db.database import Base
from backend.partners.models import Partner, ApiKey, PartnerStatus # 경로 수정
from backend.models.domain.game import Game, GameProvider
from backend.core.config import settings
from sqlalchemy import event
from backend.utils.encryption import encrypt_aes_gcm, decrypt_aes_gcm
from backend.core import security # security 임포트 추가
from backend.i18n import Translator # Translator 임포트 추가
from backend.partners.service import PartnerService # 경로 수정
from backend.db.repositories.partner_repository import PartnerRepository
import subprocess # subprocess 임포트 추가
import inspect # inspect 추가
from builtins import anext # anext 임포트 추가
from backend.services.auth.api_key_service import APIKeyService
from backend.models.domain.wallet import Wallet, Transaction, TransactionType, TransactionStatus # Wallet 모델 import 추가

# 테스트 DB URL (이제 PostgreSQL 사용)
# TEST_DB_URL = settings.TEST_DATABASE_URL ... # 기존 로직 제거

@pytest.fixture(scope="function") # 스코프를 function으로 변경
def test_settings() -> Settings:
    """각 테스트 함수를 위한 격리된 Settings 객체 생성 및 환경 변수 설정"""
    original_vars = {}
    valid_aes_key = base64.b64encode(os.urandom(32)).decode('utf-8')
    valid_enc_key = base64.b64encode(os.urandom(32)).decode('utf-8')
    # postgres 사용자로 변경
    test_db_url = "postgresql+asyncpg://postgres:qwqw6171@127.0.0.1/mydatabase" # 사용자명 변경 (postgres)
    test_redis_url = "redis://mockredis:6379/0"
    env_vars = {
        "REDIS_URL": test_redis_url,
        "AESGCM_KEY_B64": valid_aes_key,
        "ENCRYPTION_KEY": valid_enc_key,
        "DATABASE_URL": test_db_url, # PostgreSQL URL 설정 (IP 사용, postgres 사용자)
        "API_KEY_EXPIRY_DAYS": "30",
        "TOKEN_EXPIRY_MINUTES": "60",
        "ENVIRONMENT": "test",
        "DEFAULT_RETURN_URL": "https://test-return.com",
    }
    print("\n[테스트 Settings 설정 - 함수 스코프] 환경 변수 설정 중...")
    # 로그에는 비밀번호 마스킹 유지 (사용자명은 표시됨)
    print(f"[테스트 Settings 설정] Setting DATABASE_URL to: postgresql+asyncpg://postgres:****@127.0.0.1/mydatabase")
    for key, value in env_vars.items():
        original_vars[key] = os.environ.get(key)
        os.environ[key] = value

    # 새 Settings 객체 생성 (이제 Pydantic이 PostgreSQL URL을 로드)
    settings_instance = Settings()
    # 로드된 DB URL 출력 (postgres 사용자 반영)
    loaded_db_url = getattr(settings_instance, 'DATABASE_URL', 'Not Loaded')
    print(f"[테스트 Settings 설정] Created Settings instance. DATABASE_URL: {loaded_db_url}, AES Key: {getattr(settings_instance, 'AESGCM_KEY_B64', 'Not Loaded')[:5]}...")

    yield settings_instance # 생성된 인스턴스를 반환

    # 테스트 후 원래 환경 변수 복원
    print("\n[테스트 Settings 설정 - 함수 스코프] 환경 변수 복원 중...")
    for key, original_value in original_vars.items():
        if original_value is None:
            if key in os.environ:
                del os.environ[key]
        else:
            os.environ[key] = original_value


# setup_test_environment 픽스처 제거 또는 수정 (환경변수 설정만 남기거나)
# @pytest.fixture(autouse=True, scope="session")
# def setup_test_environment(): ...
# -> test_settings 픽스처가 환경변수 설정을 담당하므로 기존 setup_test_environment는 제거

@pytest.fixture(autouse=True, scope="session")
def patch_security_globally():
    """테스트 전역에 적용되는 보안 함수 패치"""
    # create_refresh_token 관련 패치 제거
    with patch('backend.core.security.get_password_hash') as mock_hash, \
         patch('backend.core.security.verify_password') as mock_verify, \
         patch('backend.core.security.create_access_token') as mock_token:

        mock_hash.side_effect = lambda pwd: f"hashed_{pwd}" # 해싱 시뮬레이션
        mock_verify.return_value = True # 패스워드 검증이 항상 성공한다고 가정
        mock_token.return_value = "mock_access_token" # 더미 토큰 반환

        yield (mock_hash, mock_verify, mock_token)

@pytest.fixture(autouse=True)
def reset_singletons():
    """테스트 간 격리를 위한 싱글톤 초기화"""
    global _redis_client # _engine, _db 제거
    _redis_client = None
    # _engine = None 제거
    # _db = None 제거
    yield

@pytest.fixture(scope="session")
def event_loop(request) -> Generator:
    """모든 테스트 세션에 대해 단일 이벤트 루프 생성"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="function") # 스코프를 function으로 변경
async def db_engine(test_settings: Settings, request):
    """테스트용 데이터베이스 엔진 생성 및 스키마 생성 (함수 스코프)"""
    # test_settings 객체에서 데이터베이스 URL 가져오기
    db_url = test_settings.DATABASE_URL
    print(f"\n[DB 엔진 설정] 테스트 DB URL from test_settings: {db_url} (함수 스코프)")

    # db_url이 None인 경우 처리 (예외 발생 또는 기본값 사용)
    if db_url is None:
        raise ValueError("DATABASE_URL is not set in test_settings")

    # db_url 타입을 문자열로 변환
    db_url_str = str(db_url)

    # 엔진 생성 시 db_url_str 사용 (수정됨)
    engine = create_async_engine(
        db_url_str, # 문자열로 변환된 URL 사용
        echo=False,
        # connect_args는 SQLite에만 필요하므로 scheme 확인
        connect_args={"check_same_thread": False} if db_url.scheme.startswith("sqlite") else {}
    )

    # SQLite에서 외래키 제약조건 활성화 리스너 추가 (scheme 확인)
    if db_url.scheme.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    # PostgreSQL 사용 시 Alembic으로 스키마 관리
    print("[DB 엔진 설정] Running Alembic migrations...")
    try:
        # Alembic 서브프로세스 실행 전 환경 변수 확인
        print(f"[DB 엔진 설정] DATABASE_URL for Alembic subprocess: {os.environ.get('DATABASE_URL')}")
        
        # 먼저 모든 마이그레이션 롤백 (초기 상태로)
        print("[DB 엔진 설정] Rolling back all migrations (downgrade base)...")
        downgrade_result = subprocess.run(["alembic", "downgrade", "base"], check=False, capture_output=True, text=True, env=os.environ.copy()) # check=False, 실패해도 계속 진행
        if downgrade_result.returncode != 0:
            print(f"[DB 엔진 설정] Alembic downgrade base might have failed (proceeding anyway): {downgrade_result.stderr}")
        else:
            print("[DB 엔진 설정] Alembic downgrade base completed.")

        # 여기에 ENUM 타입 삭제 코드 추가
        print("[DB 엔진 설정] Cleaning up any existing ENUM types...")
        cleanup_sql = """
import asyncio
import asyncpg
import os

async def drop_enum_types():
    # 환경 변수에서 DB 접속 정보 읽기 (테스트 환경 고려)
    db_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:qwqw6171@127.0.0.1/mydatabase')
    conn = None # Initialize conn to None
    try:
        conn = await asyncpg.connect(db_url)
        # CASCADE 옵션을 사용하여 의존성 있는 객체도 함께 삭제
        await conn.execute('DROP TYPE IF EXISTS gamestatus CASCADE;')
        print("Dropped gamestatus enum type (if existed)")
    except Exception as e:
        # 오류 발생 시에도 테스트 진행을 위해 에러 메시지만 출력
        print(f"Warning: Error dropping enum type 'gamestatus': {e}. Continuing test setup.")
    finally:
        if conn:
            await conn.close()

# Windows에서 asyncio 이벤트 루프 정책 설정 (Pytest 환경 고려)
if os.name == 'nt':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

asyncio.run(drop_enum_types())
"""
        # check=False로 설정하여 enum 삭제 실패가 전체 테스트를 중단시키지 않도록 함
        cleanup_result = subprocess.run(["python", "-c", cleanup_sql], check=False, capture_output=True, text=True, env=os.environ.copy())
        if cleanup_result.returncode != 0:
            print(f"[DB 엔진 설정] Warning: Enum cleanup script finished with errors: {cleanup_result.stderr}")
        else:
            print(f"[DB 엔진 설정] Enum cleanup script executed: {cleanup_result.stdout}")


        # 최신 상태로 마이그레이션 적용
        print("[DB 엔진 설정] Applying all migrations (upgrade head)...")
        upgrade_result = subprocess.run(["alembic", "upgrade", "head"], check=True, capture_output=True, text=True, env=os.environ.copy())
        print("[DB 엔진 설정] Alembic migrations applied successfully.")
        
    except subprocess.CalledProcessError as e:
        print(f"[DB 엔진 설정] Alembic migration failed: {e.stderr}")
        # 실패 시 상세 정보 추가 출력
        print(f"[DB 엔진 설정] Failed command: {e.cmd}")
        print(f"[DB 엔진 설정] Return code: {e.returncode}")
        print(f"[DB 엔진 설정] Stdout: {e.stdout}")
        raise
    except FileNotFoundError:
        print("[DB 엔진 설정] Error: 'alembic' command not found. Make sure Alembic is installed and in PATH.")
        raise

    # 최종 정리 작업 등록 (기존 유지)
    async def finalize_engine():
        print("\n[DB 엔진 정리] 엔진 자원 해제 중... (함수 스코프)")
        await engine.dispose()

    request.addfinalizer(lambda: asyncio.run(finalize_engine()))

    # 엔진 객체 반환
    return engine

@pytest.fixture(scope="function") # 스코프를 function으로 변경
async def db_session_factory(db_engine):
    """함수 스코프의 비동기 세션 팩토리 제공"""
    # engine = await db_engine # db_engine은 이제 await 불필요 (동일 스코프), 그러나 db_engine이 async fixture이므로 await 필요
    # -> db_engine이 async fixture이므로 await 유지
    engine = await db_engine 
    return async_sessionmaker(
        bind=engine, # 직접 engine 객체 바인딩
        class_=AsyncSession,
        expire_on_commit=False
    )

@pytest.fixture(scope="function")
async def db_session(db_session_factory):
    """
    함수 스코프의 비동기 DB 세션 제공 - 각 테스트는 롤백됨 (엔진 처리 로직 추가)
    """
    # 코루틴/제너레이터 처리 로직은 db_session_factory 픽스처 내부에 이미 구현되어 있음
    # db_session_factory는 호출 가능한 팩토리 객체를 반환함 (lambda)
    # 따라서 db_session_factory()를 호출하여 AsyncSessionMaker 인스턴스를 얻음
    # factory_instance = await db_session_factory() # 이 부분 수정
    # db_session_factory는 코루틴이 아니라 팩토리 함수를 반환하므로 await 불필요
    # factory_instance = db_session_factory() 
    # -> wallet_service_factory 수정과 일관되게, db_session_factory도 await 필요
    actual_factory = await db_session_factory 
    
    # AsyncSessionMaker 인스턴스 사용
    async with actual_factory() as session:
        # begin()은 실제 트랜잭션 시작 시 사용, 여기서는 세션 자체만 yield
        # async with session.begin(): 
        yield session
            # 테스트 함수 종료 후 자동으로 롤백 (세션 컨텍스트 매니저)
            # await session.rollback() # 명시적 롤백 불필요

@pytest.fixture(scope="function")
def app(test_settings: Settings) -> FastAPI:
    """테스트용 FastAPI 앱 인스턴스 반환 (test_settings 의존성 추가)"""
    main_app.dependency_overrides = {} # 각 테스트 시작 시 오버라이드 초기화

    # get_settings 의존성 오버라이드 추가
    def override_get_settings():
        return test_settings
    main_app.dependency_overrides[get_settings] = override_get_settings

    return main_app # main.py의 app 인스턴스 반환

@pytest.fixture(autouse=True)
def mock_redis():
    """Redis 클라이언트를 완전히 모킹합니다."""
    # Redis 클라이언트 인스턴스 생성 모킹
    redis_client_mock = AsyncMock(name="mocked_redis_client_instance")
    # 필요한 메서드들을 모킹합니다.
    redis_client_mock.get.return_value = None # 기본값: 캐시 미스
    redis_client_mock.set.return_value = True
    redis_client_mock.delete.return_value = True
    redis_client_mock.exists.return_value = 0
    redis_client_mock.incr.return_value = 1
    redis_client_mock.ttl.return_value = -2 # 키가 없거나 만료 시간 없음
    redis_client_mock.expire.return_value = True
    redis_client_mock.ping.return_value = True # 성공적인 ping 시뮬레이션
    redis_client_mock.sadd.return_value = 1
    redis_client_mock.smembers.return_value = set()
    redis_client_mock.pipeline.return_value = AsyncMock() # 파이프라인 모킹
    # 필요에 따라 다른 메서드 추가 (예: incrbyfloat)
    redis_client_mock.incrbyfloat.return_value = 1.0

    # Redis 연결 관련 함수들 모킹
    # get_redis_client 함수가 호출될 때 위에서 만든 모의 객체를 반환하도록 패치합니다.
    with patch("backend.cache.redis_cache.get_redis_client", return_value=redis_client_mock) as mock_get_redis_func:
        yield mock_get_redis_func # 패치 객체 자체를 yield (필요시 검증용)

@pytest.fixture(scope="function")
async def test_client(db_session, app: FastAPI, mock_redis): # async def로 변경
    """인증 미들웨어를 우회하고 격리된 DB 세션을 사용하는 비동기 테스트 클라이언트"""

    # AuthMiddleware 우회 로직 (기존 코드 활용 또는 필요 시 수정)
    async def bypass_auth_dispatch(self, request, call_next):
        # 테스트에 필요한 파트너 ID와 권한 설정 (필요시 test_partner 픽스처 활용)
        test_partner_id = UUID("015e60eb-ea54-4ad8-bd8f-4a1ce9b436b7") # 예시 또는 픽스처 값
        request.state.current_partner_id = test_partner_id
        request.state.permissions = {
            "wallet": ["deposit", "bet", "win", "read", "withdraw", "transactions.read"],
            # 필요한 다른 권한 추가
        }
        return await call_next(request)

    # 임시로 AuthMiddleware 패치
    original_dispatch = None
    if hasattr(AuthMiddleware, 'dispatch'): # dispatch 메소드 존재 확인
        original_dispatch = AuthMiddleware.dispatch
        AuthMiddleware.dispatch = bypass_auth_dispatch
    else:
        logger.warning("AuthMiddleware or its dispatch method not found for patching.")

    # 의존성 오버라이드 설정
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_read_session] = lambda: db_session
    app.dependency_overrides[get_write_session] = lambda: db_session
    # redis 클라이언트 오버라이드는 mock_redis 픽스처에서 자동으로 처리될 수 있음 (autouse=True 인 경우)
    # 필요하다면 명시적 오버라이드 추가: app.dependency_overrides[get_redis_client] = lambda: mock_redis

    # 비동기 클라이언트 반환 (기존)
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client # 비동기 클라이언트 반환

    # 테스트 후 정리: 패치 및 의존성 복원
    if original_dispatch:
        AuthMiddleware.dispatch = original_dispatch
    app.dependency_overrides = original_overrides
    print("[Cleanup] AuthMiddleware patch and dependencies restored for test_client")

@pytest.fixture(scope="function")
async def test_client_no_problematic_middleware(db_session, app: FastAPI, mock_redis):
    """RateLimit, AuditLog 미들웨어를 제외한 비동기 테스트 클라이언트"""
    from backend.middlewares.rate_limit_middleware import RateLimitMiddleware
    from backend.middlewares.audit_log import AuditLogMiddleware
    
    original_middleware = app.user_middleware.copy()
    original_dispatch = AuthMiddleware.dispatch # Auth 우회는 유지
    original_overrides = app.dependency_overrides.copy()
    
    removed_middlewares = []
    new_middleware_stack = []

    # 문제가 되는 미들웨어 식별 및 제거
    for middleware in app.user_middleware:
        if isinstance(middleware.cls, type) and (
            issubclass(middleware.cls, RateLimitMiddleware) or \
            issubclass(middleware.cls, AuditLogMiddleware)
        ):
            removed_middlewares.append(middleware)
            print(f"[Test Setup] Removing middleware: {middleware.cls.__name__}")
        else:
            new_middleware_stack.append(middleware)
            
    app.user_middleware = new_middleware_stack
    # FastAPI가 미들웨어 스택을 다시 빌드하도록 강제 (필요한 경우)
    # app.middleware_stack = app.build_middleware_stack() 
    # 참고: FastAPI 내부 API는 변경될 수 있음

    # AuthMiddleware 우회 로직 (기존 test_client와 동일하게 유지)
    async def bypass_auth_dispatch(self, request, call_next):
        test_partner_id = UUID("015e60eb-ea54-4ad8-bd8f-4a1ce9b436b7") 
        request.state.current_partner_id = test_partner_id
        request.state.permissions = {
            "wallet": ["deposit", "bet", "win", "read", "withdraw", "transactions.read"],
        }
        # --- 디버깅 로그 추가 --- 
        print(f"[Fixture DEBUG] bypass_auth_dispatch called for path: {request.url.path}") 
        # -----------------------
        return await call_next(request)

    # AuthMiddleware.dispatch 패치
    original_dispatch_func = AuthMiddleware.dispatch # 원본 저장
    AuthMiddleware.dispatch = bypass_auth_dispatch
    print(f"[Fixture DEBUG] Patched AuthMiddleware.dispatch. Original: {original_dispatch_func}, New: {AuthMiddleware.dispatch}")
    
    # 패치 후 실제 미들웨어 스택의 인스턴스 확인 (선택적, 복잡할 수 있음)
    auth_middleware_instance_found = False
    for mw in app.user_middleware:
        if isinstance(mw.cls, type) and issubclass(mw.cls, AuthMiddleware):
            auth_middleware_instance_found = True
            # 실제 인스턴스의 dispatch가 변경되었는지 확인은 어려울 수 있음
            # print(f"[Fixture DEBUG] Found AuthMiddleware instance in stack. Its dispatch: {mw.cls.dispatch}") # 클래스 메서드 확인
            break
    if not auth_middleware_instance_found:
        print("[Fixture DEBUG] Warning: AuthMiddleware instance not found in the modified stack.")
        
    # DB 및 Redis 의존성 오버라이드 (기존 test_client와 동일하게 유지)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_read_session] = lambda: db_session
    app.dependency_overrides[get_write_session] = lambda: db_session
    # Redis 오버라이드는 mock_redis 픽스처가 처리

    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

    # 테스트 후 정리: 미들웨어 및 의존성 복원
    print("[Cleanup] Restoring middlewares and dependencies for test_client_no_problematic_middleware")
    app.user_middleware = original_middleware
    # app.middleware_stack = app.build_middleware_stack() # 필요시 스택 재빌드
    AuthMiddleware.dispatch = original_dispatch_func # 원본 함수로 복원
    app.dependency_overrides = original_overrides

@pytest.fixture
async def auth_service_with_consistent_patching(db_session, mock_redis): # mock_redis 픽스처 사용
    """일관된 보안 패치와 모의 Redis로 AuthService 생성"""
    # 전역 패치가 autouse=True로 인해 활성화되어 있는지 확인
    # mock_redis 픽스처 이상으로 필요한 경우 Redis 특정 메서드 패치
    mock_redis.get.return_value = None # 기본 캐시 미스

    # AuthService에 PartnerRepository가 필요할 수 있으므로 이것도 모킹
    mock_partner_repo = AsyncMock()

    # 명시적 redis_client 인자로 서비스 인스턴스 생성
    service = AuthService(db=db_session, redis_client=mock_redis)
    # 생성자에서 받지 않은 경우 수동으로 repo 할당
    service.partner_repo = mock_partner_repo

    # 특정 검사를 위해 필요한 경우 글로벌 모의 객체 검색 (일반적으로 권장되지 않음)
    # global_mocks = request.getfixturevalue('patch_security_globally') # request 픽스처 필요
    # service._mocks = {
    #     'hash': global_mocks[0],
    #     'verify': global_mocks[1],
    #     'token': global_mocks[2],
    #     'redis': mock_redis
    # }

    return service

@pytest.fixture
async def wallet_service_with_tracked_commit(db_session, mock_redis): # 픽스처 사용
    """커밋 추적 기능이 있는 WalletService 인스턴스 생성"""
    # 필요한 경우 WalletRepository 모의 객체 생성
    mock_wallet_repo = AsyncMock()
    # 테스트에서 단순성을 위해 읽기와 쓰기에 동일한 db_session 사용
    service = WalletService(read_db=db_session, write_db=db_session)
    service.wallet_repo = mock_wallet_repo
    service.redis = mock_redis # 모의 redis 할당

    # 서비스에서 사용하는 write_db 세션 인스턴스의 커밋 패치
    commit_tracker = AsyncMock(name="commit_tracker")
    service.write_db.commit = commit_tracker # 인스턴스의 커밋 패치
    service._commit_tracker = commit_tracker # 잠재적 검증을 위한 트래커 연결

    # 필요한 경우 다른 의존성 모킹
    service._publish_transaction_event = AsyncMock()

    return service

@pytest.fixture
def mock_translator():
    """번역기 모의 객체"""
    mock = MagicMock(spec=Translator)
    mock.gettext = MagicMock(side_effect=lambda s: s)
    return mock

@pytest.fixture
async def test_partner(db_session) -> Partner:
    """테스트용 파트너 생성"""
    # 비동기 제너레이터를 올바르게 처리
    session = await anext(db_session)
    
    partner_id = uuid.uuid4()
    partner = Partner(
        id=partner_id,
        code=f"test-partner-{uuid.uuid4()}",
        name="테스트 파트너",
        partner_type="OPERATOR",
        status="ACTIVE",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    session.add(partner)
    await session.flush()
    api_key_value = f"test-key-{uuid.uuid4()}"
    hashed_key = f"hashed_{api_key_value}" # 일관된 모의 해시 사용
    api_key = ApiKey(
        id=uuid.uuid4(),
        partner_id=partner_id,
        key=hashed_key,
        name="테스트 API 키",
        permissions='["*"]',
        is_active=True,
        created_at=datetime.utcnow()
    )
    session.add(api_key)
    await session.commit()
    await session.refresh(partner)
    setattr(partner, 'api_key', api_key_value)
    setattr(partner, 'api_key_id', api_key.id)
    return partner

@pytest.fixture
async def test_api_key(db_session, test_partner) -> ApiKey:
    """테스트용 API 키 생성"""
    async with db_session.begin():
        api_key = ApiKey(
            id=uuid.uuid4(),
            partner_id=test_partner.id,
            key="hashed_testkey_12345",  # 해시된 키 값
            is_active=True,
            expires_at=datetime.now(timezone.utc).replace(year=2030),  # 미래 날짜
            permissions=["wallet:read", "wallet:write"],
            created_at=datetime.now(timezone.utc)
        )
        db_session.add(api_key)
        await db_session.flush()
        return api_key

@pytest.fixture
async def test_player() -> uuid.UUID:
    """테스트용 플레이어 ID"""
    return uuid.uuid4()

@pytest.fixture
async def test_wallet(db_session, test_player, test_partner) -> Wallet:
    """테스트용 지갑 생성"""
    async with db_session as session:
        wallet = Wallet(
            id=uuid.uuid4(), # 명시적으로 ID 생성
            player_id=str(test_player), # Player ID 문자열로 변환
            partner_id=test_partner.id, # Partner ID 사용
            currency="USD",
            balance=Decimal("100000.00"), # 초기 잔액 증가 (성능 테스트용)
            status="ACTIVE",
            version=0, # 버전 관리 추가
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(wallet)
        await session.commit()
        await session.refresh(wallet)
        return wallet

@pytest.fixture
async def test_wallet_instance(db_session, test_wallet):
    """테스트 지갑 인스턴스 픽스처 (DB에서 조회)"""
    from backend.models.domain.wallet import Wallet # Import inside fixture
    session = await anext(db_session) 
    wallet = await session.get(Wallet, test_wallet.id)
    if wallet is None:
            pytest.fail(f"Wallet with id {test_wallet.id} not found in DB for test_wallet_instance")
    return wallet

@pytest.fixture
async def test_game(db_session: AsyncSession) -> Game:
    """테스트용 게임 생성"""
    provider = GameProvider(
        id=uuid.uuid4(),
        code=f"prov-{uuid.uuid4()}",
        name="테스트 게임 제공자",
        integration_type="direct",
        is_active=True
    )
    db_session.add(provider)
    await db_session.flush()
    game = Game(
        id=uuid.uuid4(),
        provider_id=provider.id,
        name="테스트 게임",
        game_code=f"game-{uuid.uuid4()}",
        game_type="slot",
        is_active=True
    )
    db_session.add(game)
    await db_session.flush()
    await db_session.refresh(game)
    await db_session.refresh(provider)
    game.provider = provider
    return game

def create_test_wallet(currency="USD", balance=Decimal("100.00"), player_id=None, partner_id=None):
    """테스트용 지갑 객체 생성 헬퍼 함수"""
    return Wallet(
        id=uuid.uuid4(),
        player_id=player_id or uuid.uuid4(),
        partner_id=partner_id or uuid.uuid4(),
        balance=balance,
        currency=currency,
        is_active=True,
        is_locked=False
    )

@pytest.fixture
def transaction_data(): # mock_encryption_functions 의존성 제거
    """테스트용 트랜잭션 데이터 생성"""
    player_id = uuid.uuid4()
    partner_id = uuid.uuid4()
    wallet_id = uuid.uuid4()
    amount_plain = Decimal("100.00")
    try:
        # 실제 암호화 시도
        encrypted_amount = encrypt_aes_gcm(str(amount_plain))
        if encrypted_amount is None:
             pytest.fail("AES-GCM 암호화에 실패했습니다. AESGCM_KEY_B64 환경 변수 설정을 확인하세요.")
    except Exception as e:
        pytest.fail(f"테스트 설정 중 암호화 오류 발생: {e}")

    return {
        "id": uuid.uuid4(),
        "player_id": player_id,
        "partner_id": partner_id,
        "wallet_id": wallet_id,
        "reference_id": f"TEST-TX-{uuid.uuid4()}",
        "transaction_type": TransactionType.BET,
        "status": TransactionStatus.COMPLETED,
        "_encrypted_amount": encrypted_amount, # 실제 암호화된 값 사용
        "amount": amount_plain, # 원본 금액도 포함 (필요시)
        "currency": "USD",
        "original_balance": Decimal("1000.00"),
        "updated_balance": Decimal("900.00"),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "original_transaction_id": None,
        "session_id": None,
        "metadata": {}
    }

@pytest.fixture(autouse=True)
def setup_env():
    """테스트를 위한 환경 변수 설정"""
    original_redis_url = os.environ.get("REDIS_URL")
    os.environ["REDIS_URL"] = "redis://mockredis:6379/0" # 테스트용 더미 URL 설정
    # 여기에 암호화 키 등 다른 필요한 환경 변수 설정
    os.environ["AESGCM_KEY_B64"] = "your_base64_encoded_aes_key_here=="
    os.environ["ENCRYPTION_KEY"] = "your_fernet_encryption_key_here="

    print("[테스트 환경 설정] REDIS_URL, AESGCM_KEY_B64, ENCRYPTION_KEY 환경 변수 설정 완료.")

    yield

    # 테스트 후 환경 변수 정리
    if original_redis_url is None:
        del os.environ["REDIS_URL"]
    else:
        os.environ["REDIS_URL"] = original_redis_url
    # 필요한 경우 다른 변수 정리
    del os.environ["AESGCM_KEY_B64"]
    del os.environ["ENCRYPTION_KEY"]

@pytest.fixture
def mock_redis_client():
    """get_redis_client를 통해 얻은 Redis 클라이언트 모킹"""
    with patch('backend.cache.redis_cache.get_redis_client') as mock_get_redis:
        mock_redis = AsyncMock(name="mock_redis_client_fixture")
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock(return_value=True)
        # 필요한 경우 다른 메서드 추가, 예: incrbyfloat
        mock_redis.incrbyfloat = AsyncMock(return_value=1.0) # 예시
        mock_get_redis.return_value = mock_redis
        yield mock_redis

@pytest.fixture(scope="session", autouse=True)
def debug_routes():
    """테스트 시작 시 사용 가능한 모든 라우트 출력"""
    from backend.main import app
    print("\n--- 사용 가능한 라우트 ---")
    for route in app.routes:
        if hasattr(route, "path"):
            print(f"라우트: {route.path}, 이름: {getattr(route, 'name', 'N/A')}, 메서드: {getattr(route, 'methods', 'N/A')}")
    print("------------------------\n")

# setup_test_wallet 픽스처 수정: 딕셔너리로 반환
@pytest.fixture
async def setup_test_wallet(wallet_repo): 
    """테스트용 지갑 설정 및 정리"""
    test_wallet_id = f"concurrency_test_wallet_{uuid.uuid4()}"
    initial_balance = Decimal("100.00")
    currency = "USD"

    print(f"\n🏦 테스트 지갑 {test_wallet_id} 설정 (초기 잔액: {initial_balance})...")
    
    # 실제 객체를 생성하고 직접 반환 (딕셔너리 형태)
    test_data = {
        "wallet_id": test_wallet_id,
        "initial_balance": initial_balance,
        "currency": currency
    }
    
    yield test_data

@pytest.fixture
async def wallet_repo():
    """지갑 저장소 픽스처 (AsyncMock 객체 직접 반환)"""
    print("\n모의 wallet_repo 생성 중...")
    # WalletRepository import 확인 필요
    try:
        from backend.db.repositories.wallet_repository import WalletRepository
    except ImportError:
        # 테스트 환경에서 실제 클래스 임포트 불가능할 경우 기본 AsyncMock 사용
        WalletRepository = AsyncMock

    repo = AsyncMock(spec=WalletRepository) # 실제 WalletRepository spec 사용 권장

    # 기본 반환 값 또는 동작 설정
    repo.get_balance = AsyncMock(return_value=Decimal("1000.00"))
    repo.update_balance = AsyncMock()
    repo.create_wallet = AsyncMock()
    repo.get_wallet_by_player_id = AsyncMock(return_value={ # 예시 반환 값
        "id": uuid.uuid4(),
        "player_id": uuid.uuid4(),
        "partner_id": uuid.uuid4(),
        "currency": "USD",
        "balance": Decimal("1000.00"),
        "status": "ACTIVE",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    repo.find_transaction_by_reference_id = AsyncMock(return_value=None) # 중복 방지 확인용
    repo.create_transaction = AsyncMock(return_value={ # 예시 트랜잭션 반환 값
        "id": uuid.uuid4(),
        "wallet_id": uuid.uuid4(),
        "transaction_type": TransactionType.WIN,
        "amount": Decimal("0.00"),
        "status": TransactionStatus.COMPLETED,
        "reference_id": f"tx_{uuid.uuid4()}",
        "created_at": datetime.now(timezone.utc)
    })
    # 필요에 따라 더 많은 메서드 모킹 추가
    print("모의 wallet_repo 생성 완료.")
    return repo # await 없이 직접 모의 객체 반환

# setup_test_data 픽스처 추가 (딕셔너리 형태로 값 반환)
@pytest.fixture
async def setup_test_data():
    """테스트 데이터 설정 (게임 테스트용)"""
    player_id = f"player_{uuid.uuid4()}"
    game_id = f"game_{uuid.uuid4()}"
    wallet_id = f"wallet_for_{player_id}"
    initial_balance = Decimal("1000.00")
    currency = "USD"
    
    print(f"\n테스트 데이터 설정: 플레이어={player_id}, 게임={game_id}, 지갑={wallet_id}, 초기 잔액={initial_balance}")
    
    test_data = {
        "player_id": player_id,
        "game_id": game_id,
        "wallet_id": wallet_id,
        "initial_balance": initial_balance,
        "currency": currency
    }
    
    yield test_data

# transaction_repo 픽스처 추가
@pytest.fixture
async def transaction_repo():
    """트랜잭션 저장소 픽스처"""
    repo = AsyncMock()
    repo.create_transaction = AsyncMock(return_value={
        "id": uuid.uuid4(),
        "reference_id": f"test_tx_{uuid.uuid4()}",
        "transaction_type": TransactionType.BET,
        "amount": Decimal("10.00"),
        "status": TransactionStatus.COMPLETED
    })
    repo.find_transaction_by_reference_id = AsyncMock(return_value=None)
    # 추가 메서드 설정
    return repo

# reporting_repo 픽스처 추가
@pytest.fixture
async def reporting_repo():
    """리포팅 저장소 픽스처"""
    repo = AsyncMock()
    repo.record_game_event = AsyncMock()
    repo.record_financial_event = AsyncMock()
    # 추가 메서드 설정
    return repo

# partner_repo 픽스처 추가
@pytest.fixture
async def partner_repo():
    """파트너 저장소 픽스처"""
    repo = AsyncMock()
    repo.get_partner_by_id = AsyncMock(return_value={
        "id": uuid.uuid4(),
        "code": "TEST_PARTNER",
        "name": "테스트 파트너",
        "status": "ACTIVE"
    })
    # 추가 메서드 설정
    return repo

# partner_service 픽스처 추가
@pytest.fixture
async def partner_service():
    """파트너 서비스 픽스처"""
    service = AsyncMock()
    service.create_partner = AsyncMock(return_value={
        "id": uuid.uuid4(),
        "code": "TEST_PARTNER",
        "name": "테스트 파트너 서비스",
        "status": "ACTIVE"
    })
    # 추가 메서드 설정
    return service

# auth_service 픽스처 추가
@pytest.fixture
async def auth_service():
    """인증 서비스 픽스처"""
    service = AsyncMock()
    service.authenticate_api_key = AsyncMock(return_value=({
        "id": uuid.uuid4(),
        "key": "test_key",
        "is_active": True
    }, {
        "id": uuid.uuid4(),
        "name": "테스트 파트너",
        "status": "ACTIVE"
    }))
    # 추가 메서드 설정
    return service

# api_key_service 픽스처 추가
@pytest.fixture
async def api_key_service():
    """API 키 서비스 픽스처"""
    service = AsyncMock()
    service.create_api_key = AsyncMock(return_value={
        "id": uuid.uuid4(),
        "key": "test_api_key",
        "is_active": True
    })
    # 추가 메서드 설정
    return service

# api_key_repo 픽스처 추가
@pytest.fixture
async def api_key_repo():
    """API 키 저장소 픽스처"""
    repo = AsyncMock()
    repo.create_api_key = AsyncMock(return_value={
        "id": uuid.uuid4(),
        "key": "test_api_key",
        "is_active": True
    })
    repo.list_api_keys = AsyncMock(return_value=[{
        "id": str(uuid.uuid4()),
        "key": f"key_{uuid.uuid4()}",
        "is_active": True
    }])
    # 추가 메서드 설정
    return repo

@pytest.fixture(autouse=True) # 모든 테스트에 자동 적용
def mock_encryption():
    """암호화/복호화 함수 모킹 (AES-GCM)"""
    # 모킹할 함수 경로
    encrypt_path = 'backend.utils.encryption.encrypt_aes_gcm'
    decrypt_path = 'backend.utils.encryption.decrypt_aes_gcm'
    
    # 기본 모의 반환 값
    mock_encrypted_value = "mock_encrypted_aes_gcm_data"
    # 복호화 시 반환될 값 (예: 금액 문자열)
    mock_decrypted_value = "100.00" 

    with patch(encrypt_path) as mock_encrypt, \
         patch(decrypt_path) as mock_decrypt:
        
        # encrypt_aes_gcm 모킹: 항상 동일한 모의 암호화 문자열 반환
        mock_encrypt.return_value = mock_encrypted_value
        
        # decrypt_aes_gcm 모킹: 항상 동일한 모의 복호화 문자열 반환
        mock_decrypt.return_value = mock_decrypted_value
        
        print(f"[Mock] Encryption functions ({encrypt_path}, {decrypt_path}) are mocked.")
        
        yield mock_encrypt, mock_decrypt # 필요시 모의 객체 반환

@pytest.fixture
async def wallet_service_factory(db_session_factory):
    """지갑 서비스 팩토리 픽스처"""
    from backend.services.wallet.wallet_service import WalletService # Import inside fixture
    # 코루틴 await 제거 (테스트 코드에서 await으로 factory를 얻음)
    # actual_factory = await db_session_factory 
    
    # 직접 함수 반환 (람다 함수도 가능)
    return lambda: WalletService(
        # read_db_factory=actual_factory,
        # write_db_factory=actual_factory
        read_db_factory=db_session_factory, # 수정: 팩토리 자체를 전달
        write_db_factory=db_session_factory # 수정: 팩토리 자체를 전달
    )