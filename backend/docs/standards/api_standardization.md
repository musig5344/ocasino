# API 응답 및 예외 처리 표준화 가이드

## 1. 목표

API 전반에 걸쳐 응답 구조와 예외 처리 방식의 일관성을 확보하고, 코드의 가독성 및 유지보수성을 향상시키는 것을 목표로 합니다.

## 2. 표준 응답 형식

모든 API 엔드포인트는 표준화된 응답 형식을 따라야 합니다.

### 2.1. 성공 응답

- 단일 객체 반환 시: `StandardResponse[Schema]`
- 목록 (페이지네이션) 반환 시: `PaginatedResponse[Schema]`

**구현:**

- `response_model`에 `StandardResponse` 또는 `PaginatedResponse`를 명시합니다. (`Schema`는 실제 반환될 데이터의 Pydantic 스키마입니다.)
- API 함수 내에서는 실제 데이터 객체 또는 목록을 반환합니다.
- 응답 래핑은 `backend.utils.response`의 유틸리티 함수를 사용합니다.
    - `success_response(data: Optional[Any] = None, message: str = "Success")`: 단일 객체 응답 생성
    - `paginated_response(items: List[Any], total: int, page: int, page_size: int)`: 페이지네이션 응답 생성

**예시 (`partners/api.py`):**

```python
from backend.core.schemas import StandardResponse, PaginatedResponse
from backend.utils.response import success_response, paginated_response
from backend.partners.schemas import Partner

@router.get("/{partner_id}", response_model=StandardResponse[Partner])
async def read_partner(...):
    partner = await service.get(partner_id)
    return success_response(data=partner)

@router.get("", response_model=PaginatedResponse[Partner])
async def list_partners(...):
    partners, total = await service.list(...)
    return paginated_response(
        items=partners, 
        total=total, 
        page=pagination.get("page", 1), 
        page_size=pagination["limit"]
    )
```

### 2.2. 실패 응답 (예외 처리)

- 모든 예외는 전역 예외 핸들러를 통해 처리되며, `backend.core.schemas.ErrorResponse` 형식으로 변환됩니다.
- `ErrorResponse`는 `message` (오류 메시지), `error_code` (고유 오류 코드), `details` (선택적 상세 정보)를 포함합니다.

**구현:**

- API 엔드포인트 내에서 `try...except HTTPException` 블록을 사용하지 않습니다.
- 서비스 계층이나 API 계층에서 발생하는 특정 상황에 맞는 커스텀 예외를 발생시킵니다. (`backend.core.exceptions` 참고)
    - 예: `NotFoundError`, `ValidationError`, `ConflictError`, `PermissionDeniedError`, `BusinessLogicError` 등
- 발생된 예외는 `backend.app.exceptions`에 등록된 전역 핸들러가 처리하여 적절한 HTTP 상태 코드와 `ErrorResponse` 본문을 반환합니다.

**예시 (`partners/api.py`):**

```python
from backend.core.exceptions import PermissionDeniedError, NotFoundError

@router.post("", response_model=StandardResponse[Partner], status_code=201)
async def create_partner(...):
    if "partners.create" not in requesting_permissions:
         # HTTPExcetion 대신 PermissionDeniedError 발생
         raise PermissionDeniedError("Permission denied to create partners") 
    
    # 서비스 계층에서 발생할 수 있는 ConflictError 등은 전역 핸들러가 처리
    partner = await service.create(partner_data) 
    return success_response(data=partner, message="Partner created successfully.")

@router.get("/{partner_id}", response_model=StandardResponse[Partner])
async def read_partner(...):
    # 서비스 계층에서 발생할 수 있는 NotFoundError는 전역 핸들러가 404로 처리
    partner = await service.get(partner_id) 
    # 권한 검사 등 필요 시 PermissionDeniedError 발생
    if partner.id != requesting_partner_id and "partners.read.all" not in requesting_permissions:
         raise PermissionDeniedError("Permission denied to view this partner's details")
    return success_response(data=partner)
```

## 3. 권한 처리

- 엔드포인트 접근 권한 확인 시, 권한이 부족하면 `backend.core.exceptions.PermissionDeniedError`를 발생시킵니다.
- 이 예외는 전역 핸들러에 의해 `403 Forbidden` 상태 코드와 적절한 오류 메시지로 변환됩니다.

## 4. 린터 오류 해결 (매개변수 순서)

FastAPI의 `Depends`를 사용하는 의존성 주입 패턴은 `Non-default argument follows default argument` 린터 오류를 유발할 수 있습니다. 이를 해결하기 위해 함수 정의 시 매개변수 순서를 다음과 같이 조정합니다.

1.  경로 매개변수 (`Path`)
2.  쿼리 매개변수 (`Query`)
3.  본문 매개변수 (`Body`)
4.  의존성 주입 매개변수 (`Depends`)

**예시 (`partners/api.py`):**

```python
async def update_partner(
    # 1. Path parameter
    partner_id: UUID = Path(..., description="..."),
    # 3. Body parameter
    partner_update: PartnerUpdate,
    # 4. Depends parameters
    service: PartnerService = Depends(get_partner_service), 
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    # ... function body ...
```

## 5. 적용된 모듈 (응답/예외)

응답 및 예외 처리 표준화 가이드라인은 다음 API 모듈에 적용되었습니다.

- `backend.partners.api`
- `backend.games.api`
- `backend.wallet.api`
- `backend.reports.api`

**참고:** 일부 특수 엔드포인트 (예: 파일 다운로드, 202 Accepted 응답)는 표준 응답 래퍼를 사용하지 않을 수 있으나, 예외 처리는 동일한 전역 핸들러 메커니즘을 따릅니다.

## 6. 로깅 표준화

### 6.1. 목표

- 코드베이스 전반에 걸쳐 일관되고 구조화된 로깅 방식을 적용합니다.
- 로그 데이터의 분석 및 모니터링 효율성을 높여 운영 환경에서의 디버깅 및 문제 해결 능력을 향상시킵니다.

### 6.2. 구현

- **StructuredLogger (`backend/core/logging.py`):**
    - 표준 파이썬 로깅 라이브러리를 기반으로 구조화된 로그 데이터(JSON 형식 권장) 생성을 위한 래퍼 클래스입니다.
    - 로그 레벨, 타임스탬프, 로거 이름, 메시지 외에 호출 위치(`location`, `function`), 컨텍스트 정보(`context`), 요청 ID(`request_id`), 예외 정보(`exception`), 성능 측정(`duration_ms`) 등의 필드를 포함합니다.
    - 민감 정보(비밀번호, API 키 등)는 자동으로 필터링(`_sanitize_data`)합니다.
- **JsonFormatter (`backend/core/logging.py`):**
    - `StructuredLogger`가 생성한 구조화된 로그 데이터 또는 일반 로그 레코드를 JSON 문자열로 변환하는 포맷터입니다.
    - 외부 라이브러리 로그도 기본적인 JSON 형식으로 변환합니다.
- **configure_logging (`backend/core/logging.py`):**
    - 애플리케이션 전체의 로깅 설정을 담당하는 함수입니다.
    - 로그 레벨, JSON 포맷터 사용 여부, 로그 파일 출력 여부 등을 설정합니다.
    - 애플리케이션 시작 시 (`main.py`) 호출됩니다.

### 6.3. BaseService 통합

- `BaseService.__init__`에서 `StructuredLogger` 인스턴스를 초기화합니다 (`self.logger`).
- `get`, `list`, `create`, `update`, `delete` 등 주요 CRUD 메서드 내부에 `self.logger`를 사용한 로깅 구문을 추가했습니다.
    - 작업 시작/성공/실패 시점, 관련 ID, 컨텍스트 정보, 소요 시간(`duration_ms`), 예외 정보 등을 기록합니다.
    - 모든 하위 서비스 클래스는 자동으로 이 표준화된 로깅을 상속받습니다.

**예시 (`backend/core/service.py`):**

```python
from backend.core.logging import StructuredLogger
from datetime import datetime

class BaseService(...):
    def __init__(self, ...):
        # ...
        self.logger = StructuredLogger(f"service.{self.service_name}")
        self.logger.debug("Initialized service", service_name=self.service_name)

    async def create(self, data: C) -> S:
        start_time = datetime.utcnow()
        self.logger.info("Attempting to create", operation="create", context={"data": ...})
        try:
            # ... creation logic ...
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            self.logger.info("Successfully created", operation="create", entity_id=..., duration_ms=elapsed)
            return result
        except Exception as e:
            self.logger.error("Failed to create", operation="create", exception=e, context={"data": ...})
            raise
```

### 6.4. 설정 방법

- `backend/main.py` 파일의 애플리케이션 초기화 부분에서 `configure_logging` 함수를 호출합니다.
- 로그 레벨(`LOG_LEVEL`), JSON 로그 사용 여부(`JSON_LOGS`), 로그 파일 경로(`LOG_FILE`) 등은 `backend/core/config.py`의 `settings` 객체를 통해 주입됩니다.

```python
# backend/main.py
from backend.core.logging import configure_logging
from backend.core.config import settings

# 애플리케이션 생성 전 로깅 설정 적용
configure_logging(
    log_level=settings.LOG_LEVEL,
    json_logs=settings.JSON_LOGS,
    log_file=settings.LOG_FILE
)

# ... rest of app setup ...
```

### 6.5. 기대 효과

- 모든 서비스에서 일관된 로깅 패턴 적용으로 디버깅 용이성 증대.
- 구조화된 로그 데이터를 활용하여 Elasticsearch, Datadog 등 로그 분석 시스템과의 연동 및 모니터링 강화.
- 성능 관련 지표(소요 시간 등) 로깅을 통한 병목 현상 분석 기반 마련. 