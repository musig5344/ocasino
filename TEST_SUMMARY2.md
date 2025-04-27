# 테스트 모범 사례 요약

## FastAPI 미들웨어 우회 테스트 패턴

### 배경
FastAPI/Starlette 애플리케이션 테스트 시 미들웨어(특히 요청 본문을 처리하는 미들웨어)로 인해 "Unexpected message received: http.request" 같은 오류가 자주 발생합니다. 이는 ASGI 요청 처리 방식과 미들웨어의 복잡한 상호작용 때문입니다.

### 해결 방법: 미들웨어 우회 패턴

API 엔드포인트를 테스트할 때는 미들웨어를 패치하는 대신 미들웨어가 없는 새 FastAPI 애플리케이션을 생성하여 테스트하는 것이 더 효과적입니다:

```python
# 테스트용 미들웨어 없는 애플리케이션 생성
from fastapi import FastAPI
from starlette.testclient import TestClient

test_app = FastAPI()

# 원본 앱의 라우터만 복사
for route in app.routes:
    test_app.routes.append(route)

# 의존성 오버라이드 복사
test_app.dependency_overrides = app.dependency_overrides.copy()

# 미들웨어 없는 테스트 클라이언트 생성
clean_test_client = TestClient(test_app)

# 이 클라이언트로 API 호출
response = clean_test_client.post(
    "/api/endpoint",
    json=request_data,
    headers=headers
)
```

## 테스트 시 기타 고려사항

### 데이터 형식 비교
API 응답과 예상 값 비교 시 형식 차이(예: 문자열 vs 부동소수점)에 주의하세요:

```python
# 방법 1: 둘 다 float로 변환
assert float(response_data["balance"]) == float(expected_balance)

# 방법 2: 문자열 비교
assert str(response_data["balance"]) == str(expected_balance)
```

### 의존성 오버라이드 관리
테스트 후 원래 상태로 복원하는 것을 잊지 마세요:

```python
# 원본 설정 저장
original_overrides = app.dependency_overrides.copy()

try:
    # 테스트 코드...
finally:
    # 의존성 복원
    app.dependency_overrides = original_overrides
```

### 비동기 모킹
비동기 함수를 모킹할 때는 AsyncMock을 사용하세요:

```python
from unittest.mock import AsyncMock

mock_service = AsyncMock()
mock_service.some_method.return_value = expected_result
```

## 권장 패턴 사용 예시

```python
@pytest.mark.asyncio
@patch('services.some_service.method', new_callable=AsyncMock)
async def test_some_api(mock_method, test_client):
    """API 테스트 (미들웨어 우회 방식)"""
    # 원본 설정 저장
    original_overrides = app.dependency_overrides.copy()

    # 의존성 오버라이드 설정
    mock_instance = AsyncMock()
    async def override_get_service():
        return mock_instance
    app.dependency_overrides[get_service] = override_get_service

    # 미들웨어 없는 테스트 애플리케이션 생성
    test_app = FastAPI()
    for route in app.routes:
        test_app.routes.append(route)
    test_app.dependency_overrides = app.dependency_overrides
    clean_test_client = TestClient(test_app)

    try:
        # 테스트 로직
        mock_method.return_value = expected_result
        
        response = clean_test_client.post(
            "/api/endpoint",
            json=request_data,
            headers=headers
        )
        
        # 검증
        assert response.status_code == 200
        response_data = response.json()
        assert float(response_data["value"]) == float(expected_value)
        mock_method.assert_called_once()
        
    finally:
        # 원래 설정 복원
        app.dependency_overrides = original_overrides
```

## 다음 작업 제안

이 문서를 작성한 후에 다음 작업을 수행하는 것을 추천합니다:

1. **기존 테스트 리팩토링**: 
   * 현재 미들웨어 패치를 사용하는 테스트들을 식별하고, 새로운 미들웨어 우회 패턴으로 리팩토링하세요.
   * 테스트 클래스나 공유 Fixture로 이 패턴을 추출하여 코드 중복을 줄이세요.

2. **테스트 헬퍼 유틸리티 만들기**:
   * 미들웨어 없는 테스트 클라이언트를 쉽게 생성할 수 있는 유틸리티 함수를 만드세요:
   ```python
   def create_middleware_free_test_client(app):
       """미들웨어가 없는 테스트 클라이언트 생성"""
       test_app = FastAPI()
       for route in app.routes:
           test_app.routes.append(route)
       test_app.dependency_overrides = app.dependency_overrides.copy()
       return TestClient(test_app)
   ```

3. **CI 파이프라인에 테스트 추가**:
   * 안정적인 테스트가 확보되었으니 CI/CD 파이프라인에 통합하여 자동으로 실행되게 하세요.
   * GitHub Actions, Jenkins 등의 CI 도구에 이 테스트를 추가하세요.

4. **팀 공유 및 교육**:
   * 이번에 배운 패턴을 팀의 다른 구성원들과 공유하세요.
   * 코드 리뷰 시 이 패턴을 적용하도록 권장하세요.

이 문서와 후속 작업을 통해 테스트의 안정성과 유지보수성을 크게 향상시킬 수 있을 것입니다. 