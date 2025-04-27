# tests/api/routers/test_health.py
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import AsyncMock, patch
from backend.main import app as main_app
from fastapi import status
from backend.core.config import settings

# 미들웨어 없는 테스트 클라이언트 생성 헬퍼 함수
def create_middleware_free_test_client(app):
    """미들웨어가 없는 테스트 클라이언트 생성"""
    test_app = FastAPI()
    # 원본 앱의 라우터만 복사
    for route in app.routes:
        test_app.routes.append(route)
    # 의존성 오버라이드 복사
    test_app.dependency_overrides = app.dependency_overrides.copy()
    return TestClient(test_app)

# 테스트 클라이언트 픽스처 - 미들웨어 없는 버전 사용
@pytest.fixture(scope="module")
def client():
    # 미들웨어 없는 클라이언트 생성
    clean_client = create_middleware_free_test_client(main_app)
    yield clean_client

# DB 상태 확인 의존성 모킹 (필요한 경우)
@pytest.fixture
def mock_db_status():
    async def _mock_db_status():
        return "connected"
    return _mock_db_status

# 캐시 상태 확인 의존성 모킹 (필요한 경우)
@pytest.fixture
def mock_cache_status():
    async def _mock_cache_status():
        return "connected"
    return _mock_cache_status

# 기본 상태 확인 테스트
@pytest.mark.asyncio
async def test_basic_health_check(client):
    """기본 /health 엔드포인트 테스트"""
    print("\n[Test] 기본 상태 확인 엔드포인트 테스트 (/api/health/health/)...")
    
    # 직접 호출 (URL 수정)
    response = client.get("/api/health/health/")
    
    print(f"[Test] 응답 상태 코드: {response.status_code}")
    print(f"[Test] 응답 본문: {response.text}")
    
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "ok"
    
    print("[Test] 기본 상태 확인 테스트 완료")

# 상세 상태 확인 테스트
@pytest.mark.asyncio
async def test_detailed_health_check(client):
    """상세 /health/detailed 엔드포인트 테스트"""
    print("\n[Test] 상세 상태 확인 엔드포인트 테스트 (/api/health/health/detailed)...")

    # 의존성 오버라이드 대신 직접 패치 사용
    with patch("backend.api.routers.health.check_database_connectivity",
               return_value={"status": "healthy", "message": "Connected", "latency_ms": 0.5}) as mock_db_check, \
         patch("backend.api.routers.health.check_redis_connectivity",
               return_value={"status": "healthy", "message": "Connected", "latency_ms": 0.3}) as mock_redis_check:

        # API 호출
        response = client.get("/api/health/health/detailed")

        print(f"[Test] 응답 상태 코드: {response.status_code}")
        print(f"[Test] 응답 본문: {response.text}")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["overall_status"] == "ok" # 전체 상태 확인
        # 상세 컴포넌트 상태 확인 (선택 사항)
        assert response_data["components"]["database"]["status"] == "healthy"
        assert response_data["components"]["redis"]["status"] == "healthy"

    print("[Test] 상세 상태 확인 테스트 완료")

# 테스트 실패 시나리오: DB 연결 실패 가정
@pytest.mark.asyncio
async def test_db_connection_failure(client):
    print("\n[Test] DB 연결 실패 테스트...")

    # DB 연결 실패 시나리오 패치
    with patch("backend.api.routers.health.check_database_connectivity",
                 return_value={"status": "error", "message": "DB connection failed"}) as mock_db_fail, \
         patch("backend.api.routers.health.check_redis_connectivity", # Redis는 정상이라고 가정
               return_value={"status": "healthy", "message": "Connected", "latency_ms": 0.3}) as mock_redis_ok:

        response = client.get("/api/health/health/detailed")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = response.json()

    print(f"[Test] 응답 상태 코드: {response.status_code}")
    print(f"[Test] 응답 본문: {response.text}")

    # 수정된 Assertion: 중첩 구조 및 올바른 키 사용
    assert data["overall_status"] == "error"
    assert data["components"]["database"]["status"] == "error"
    assert data["components"]["database"]["message"] == "DB connection failed"
    # Redis 상태도 확인 (정상이어야 함)
    assert data["components"]["redis"]["status"] == "healthy"

    print("[Test] DB 연결 실패 테스트 완료")