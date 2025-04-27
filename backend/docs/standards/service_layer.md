# 서비스 계층 표준화 가이드라인

## 소개

이 문서는 애플리케이션의 서비스 계층 구현에 대한 표준화 지침을 제공합니다. 일관된 패턴과 관행을 통해 코드의 가독성, 유지보수성 및 테스트 용이성을 향상시키는 것이 목적입니다.

## 1. 서비스 계층 구조

### 1.1 서비스 유형 분류

서비스는 다음과 같이 분류됩니다:

1.  **CRUD 서비스**: 기본적인 데이터 관리 작업을 담당, `BaseService` 상속
    *   예: `PartnerService`, `GameService` (CRUD 부분)

2.  **비즈니스 프로세스 서비스**: 복잡한 비즈니스 로직 담당, 독립적 구현
    *   예: `GameLaunchService`, `WalletTransactionService` (가정)

3.  **통합 서비스**: 외부 시스템과의 통합 담당, 독립적 구현
    *   예: `PaymentGatewayService`, `GameProviderIntegrationService` (가정)

### 1.2 BaseService 구성

```python
class BaseService(Generic[T, S, C, U]):
    """
    모든 CRUD 서비스의 기본 클래스

    T: 데이터베이스 모델 타입
    S: 응답 스키마 타입
    C: 생성 스키마 타입
    U: 업데이트 스키마 타입
    """
    service_name: str = "base"
    entity_name: str = "record"
    id_field: str = "id"
    not_found_exception_class: Type[Exception] = NotFoundError

    def __init__(
        self,
        db: AsyncSession,
        model_class: Type[T],
        response_schema_class: Type[S],
        create_schema_class: Optional[Type[C]] = None,
        update_schema_class: Optional[Type[U]] = None,
    ): ...

    async def get(self, id_value: Union[str, int, UUID]) -> S: ...
    async def list(self, skip: int = 0, limit: int = 100,
                   filters: Optional[Dict[str, Any]] = None,
                   sort_by: Optional[str] = None,
                   sort_order: str = "asc") -> Tuple[List[S], int]: ...
    async def create(self, data: C) -> S: ...
    async def update(self, id_value: Union[str, int, UUID], data: U) -> S: ...
    async def delete(self, id_value: Union[str, int, UUID]) -> bool: ...
    async def get_or_404(self, id_value: Union[str, int, UUID]) -> T: ...

    # 추상 메소드 (Subclass 구현 필요)
    async def _find_one(self, query: Dict[str, Any]) -> Optional[T]: ...
    async def _find_many(self, skip: int, limit: int,
                         filters: Optional[Dict[str, Any]],
                         sort_by: Optional[str], sort_order: str) -> Tuple[List[T], int]: ...
    async def _create_entity(self, data: Dict[str, Any]) -> T: ...
    async def _update_entity(self, entity: T, data: Dict[str, Any]) -> T: ...
    async def _delete_entity(self, entity: T) -> bool: ...

    # Validation Hooks (Optional Override)
    async def _validate_create_data(self, data: C) -> None: ...
    async def _validate_update_data(self, entity: T, data: U) -> None: ...
```

**주요 속성 및 메소드**

*   `get(id)`: ID로 단일 항목 조회
*   `list(...)`: 필터링, 정렬, 페이지네이션 지원 목록 조회
*   `create(data)`: 새 항목 생성 (트랜잭션, 유효성 검사, `_create_entity` 호출 포함)
*   `update(id, data)`: 항목 업데이트 (트랜잭션, 유효성 검사, `_update_entity` 호출 포함)
*   `delete(id)`: 항목 삭제 (트랜잭션, `_delete_entity` 호출 포함)
*   `get_or_404(id)`: ID로 항목 조회하거나 `not_found_exception_class` 발생 (`_find_one` 호출)

### 1.3 서비스 책임 범위

*   **CRUD 서비스**: 데이터 유효성 검사 (`_validate_*` hooks), 기본 비즈니스 규칙, 레포지토리를 통한 CRUD 작업 위임 (`_find_*`, `_create_*`, `_update_*`, `_delete_*` 구현).
*   **비즈니스 프로세스 서비스**: 여러 단계로 구성된 복잡한 워크플로우 조정, 다른 서비스(CRUD 포함) 또는 레포지토리 호출, 도메인 규칙 적용.
*   **통합 서비스**: 외부 API 통신, 요청/응답 데이터 변환 및 매핑, 외부 시스템 오류 처리.

## 2. 구현 패턴

### 2.1 레포지토리 통합

서비스는 데이터 액세스를 위해 레포지토리 패턴을 사용하며, `BaseService`의 추상 메소드를 통해 레포지토리 메소드를 호출합니다.

```python
# PartnerService 예시
class PartnerService(BaseService[PartnerModel, PartnerSchema, PartnerCreate, PartnerUpdate]):
    def __init__(self, db: AsyncSession, partner_repo: Optional[PartnerRepository] = None):
        super().__init__(...) # BaseService 초기화
        self.partner_repo = partner_repo or PartnerRepository(db) # Repository 주입

    # BaseService 추상 메소드 구현 예시
    async def _find_one(self, query: Dict[str, Any]) -> Optional[PartnerModel]:
        # BaseService의 get_or_404는 {id_field: value} 형태의 query를 전달
        if len(query) == 1 and self.id_field in query:
            return await self.partner_repo.get_partner_by_id(query[self.id_field])
        # 다른 필요한 조회 조건 처리...
        return None

    async def _find_many(self, skip: int, limit: int, filters, sort_by, sort_order) -> Tuple[List[PartnerModel], int]:
        # Repository의 list 메소드가 목록과 총 개수를 반환한다고 가정
        return await self.partner_repo.list_partners(
            skip=skip, limit=limit, filters=filters, sort_by=sort_by, sort_order=sort_order
        )

    async def _create_entity(self, data: Dict[str, Any]) -> PartnerModel:
        new_partner = self.model_class(**data)
        return await self.partner_repo.create_partner(new_partner)

    async def _update_entity(self, entity: PartnerModel, data: Dict[str, Any]) -> PartnerModel:
        # 파트너 코드 업데이트 방지 등 서비스 로직 포함 가능
        if 'code' in data:
            del data['code']
        return await self.partner_repo.update_partner(entity, data)

    async def _delete_entity(self, entity: PartnerModel) -> bool:
        # 논리적 삭제 구현
        update_data = {"status": PartnerStatus.TERMINATED, "is_active": False}
        updated_partner = await self.partner_repo.update_partner(entity, update_data)
        return updated_partner is not None
```

**레포지토리 요구사항:**

*   `find_one` (또는 `get_by_id` 등): 단일 엔티티 조회
*   `list_entities` (또는 `find_many`): 목록과 총 개수 반환 `Tuple[List[T], int]`
*   `create_entity`: 엔티티 생성
*   `update_entity`: 엔티티 업데이트
*   `delete_entity`: 엔티티 삭제 (논리적 또는 물리적)

### 2.2 의존성 주입

서비스 생성자는 다음 원칙을 따릅니다:

*   **필수 의존성** (`AsyncSession` 등)은 생성자 매개변수로 명시적으로 선언합니다.
*   **선택적 의존성** (다른 서비스, 레포지토리, 캐시 클라이언트 등)은 기본값(`None`)을 제공하고, 필요시 생성자 내에서 기본 구현체로 초기화합니다.
*   외부 설정이나 팩토리를 통해 주입하는 것을 권장합니다 (예: FastAPI의 `Depends`).

```python
# GameService 예시
def __init__(
    self,
    db: AsyncSession,  # 필수
    redis_client: Optional[redis.Redis] = None, # 선택적 (기본값 제공)
    game_repo: Optional[GameRepository] = None, # 선택적
    wallet_repo: Optional[WalletRepository] = None, # 선택적
    partner_repo: Optional[PartnerRepository] = None, # 선택적
    wallet_service: Optional[WalletService] = None # 선택적
):
    super().__init__(db=db, model_class=Game, ...) # BaseService 초기화
    self.redis_client = redis_client or get_redis_client() # 기본값 사용 또는 생성
    self.game_repo = game_repo or GameRepository(db)
    self.wallet_repo = wallet_repo or WalletRepository(db)
    self.partner_repo = partner_repo or PartnerRepository(db)
    self.wallet_service = wallet_service or WalletService(db) # 다른 서비스도 주입 가능
```

### 2.3 트랜잭션 관리

`BaseService`의 `create`, `update`, `delete` 메소드는 내부적으로 `db.commit()` 및 `db.rollback()`을 사용하여 기본적인 트랜잭션 관리를 제공합니다.

```python
# BaseService.create 예시 (간략화)
async def create(self, data: C) -> S:
    await self._validate_create_data(data)
    entity_data = data.model_dump()
    try:
        created_entity = await self._create_entity(entity_data) # Subclass 구현 호출
        await self.db.commit() # 성공 시 커밋
        await self.db.refresh(created_entity)
        return self._entity_to_schema(created_entity)
    except Exception as e:
        await self.db.rollback() # 실패 시 롤백
        raise DatabaseError(...) from e
```

**주의:** 여러 레포지토리나 서비스 메소드를 호출하는 복잡한 비즈니스 로직의 경우, 해당 로직을 포함하는 서비스 메소드 전체를 단일 트랜잭션으로 묶어야 할 수 있습니다. 이는 `async with db.begin():` 컨텍스트 매니저를 사용하거나, API 계층의 의존성 주입 시스템에서 트랜잭션을 관리하는 방식으로 구현할 수 있습니다.

## 3. 오류 처리 전략

### 3.1 서비스 계층 예외

서비스 계층은 비즈니스 로직 또는 데이터 관련 오류 발생 시 `backend.core.exceptions`에 정의된 표준 예외를 발생시켜야 합니다. HTTP 관련 예외(`fastapi.HTTPException`)는 절대 사용하지 않습니다.

*   `NotFoundError` (및 하위 클래스 `PartnerNotFoundError`, `GameNotFoundError` 등): 요청한 리소스를 찾을 수 없음 (ID 조회 실패 등).
*   `ValidationError`: 입력 데이터 유효성 검사 실패 (형식 오류, 필수 값 누락 등). Pydantic 유효성 검사 실패 시 발생 가능.
*   `ConflictError`: 고유성 제약 조건 위반 (예: 중복된 파트너 코드, 이미 존재하는 외부 게임 ID).
*   `PermissionDeniedError`: 요청자가 해당 작업을 수행할 권한이 없음 (서비스 레벨에서 권한 확인 시).
*   `BusinessLogicError`: 일반적인 비즈니스 규칙 위반 (예: 비활성 파트너의 API 키 생성 시도).
*   `AuthenticationError`: 인증 실패 (예: 잘못된 API 키, 만료된 토큰 - 콜백 처리 등 내부 로직에서).
*   `DatabaseError`: 데이터베이스 작업 중 예측하지 못한 오류 발생.

### 3.2 API 계층으로의 예외 전파

API 라우터 핸들러는 서비스 메소드를 호출하고, 서비스 계층에서 발생한 표준 예외를 `try...except` 블록으로 잡아 적절한 `fastapi.HTTPException`으로 변환하여 클라이언트에 반환합니다.

```python
# partners/api.py 예시
@router.get("/{partner_id}", response_model=PartnerSchema)
async def get_partner_details(
    partner_id: UUID,
    service: PartnerService = Depends(get_partner_service)
):
    try:
        partner = await service.get(partner_id) # BaseService.get 호출
        return partner
    except PartnerNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionDeniedError as e: # Hypothetical
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e: # Catch-all for unexpected errors
        logger.exception(f"Error getting partner {partner_id}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@router.post("", response_model=PartnerSchema, status_code=status.HTTP_201_CREATED)
async def register_partner(
    partner_data: PartnerCreate,
    service: PartnerService = Depends(get_partner_service)
):
    try:
        new_partner = await service.create(partner_data) # BaseService.create 호출
        return new_partner
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValidationError as e: # Could come from _validate_create_data
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except DatabaseError as e:
         logger.error(f"Database error creating partner: {e}")
         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create partner due to database issue.")
    except Exception as e:
        logger.exception("Unexpected error creating partner")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")
```

## 4. 실제 예제

### 4.1 PartnerService 구현

`PartnerService`는 `BaseService`를 상속하여 기본적인 파트너 CRUD 기능을 제공하며, 파트너 코드 중복 검사(`_validate_create_data`), 코드 업데이트 방지(`_update_entity`), 논리적 삭제(`_delete_entity`)와 같은 특정 로직을 구현합니다. 또한 API 키 생성/관리(`create_api_key`, `validate_api_key`), 설정 관리 등 파트너 관련 비즈니스 로직 메소드를 포함합니다. (구현 세부사항은 `backend/partners/service.py` 참조)

### 4.2 GameService 구현

`GameService`도 `BaseService`를 상속하여 게임 정보 CRUD를 처리합니다 (`_find_*`, `_create_*`, `_update_*`, `_delete_*` 구현). 제공자 존재 여부 확인(`_create_entity`)과 같은 유효성 검사를 포함합니다. 핵심 기능인 게임 실행 URL 생성(`launch_game`) 및 게임 제공사 콜백 처리(`process_callback`)와 같은 복잡한 비즈니스 로직은 별도 메소드로 구현되어 있으며, 필요시 `BaseService`의 `get_or_404` 등을 활용합니다. (구현 세부사항은 `backend/services/game/game_service.py` 참조)

## 5. 모범 사례 및 안티 패턴

### 5.1 지향해야 할 패턴 (Do's)

*   **단일 책임 원칙 (SRP) 준수**: 각 서비스는 특정 도메인 영역(예: 파트너 관리, 게임 관리, 지갑 관리)에 집중합니다.
*   **계층 분리 유지**: 서비스는 비즈니스 로직과 도메인 규칙에만 집중하고, 프레젠테이션(API), 데이터 액세스(Repository), 인프라(Cache, 외부 API 호출) 관련 관심사를 직접 다루지 않습니다 (주입받아 사용).
*   **명시적 의존성 주입**: 필요한 모든 의존성(DB 세션, 레포지토리, 다른 서비스 등)을 생성자에서 명시적으로 주입받습니다.
*   **추상화 활용**: `BaseService`와 같은 추상화를 통해 반복적인 CRUD 코드를 줄이고 일관성을 유지합니다.
*   **도메인 예외 사용**: 오류 상황은 표준 도메인 예외(`NotFoundError` 등)를 통해 알립니다.

### 5.2 피해야 할 패턴 (Don'ts)

*   **서비스에서 HTTP 예외 발생**: 서비스는 비즈니스 로직에만 집중해야 합니다. `fastapi.HTTPException`은 API 계층에서만 사용합니다.
*   **서비스 간 과도한 직접 호출**: 서비스들이 서로 거미줄처럼 얽히면 테스트와 유지보수가 어려워집니다. 필요하다면 인터페이스나 이벤트 기반 통신을 고려합니다.
*   **입력 데이터 유효성 검사 누락**: API 계층의 Pydantic 검증 외에도, 서비스 계층에서 비즈니스 규칙 기반의 추가 유효성 검사(`_validate_*` hooks 등)를 수행해야 합니다.
*   **트랜잭션 관리 부재**: 데이터 일관성이 중요한 상태 변경 작업(생성, 수정, 삭제, 여러 작업 조합)은 반드시 적절한 트랜잭션 범위 내에서 수행되어야 합니다.
*   **Anemic Domain Model 피하기**: 서비스가 모든 로직을 가지고 모델은 단순 데이터 컨테이너 역할만 하는 것을 지양합니다. 가능한 경우 모델 자체에 간단한 비즈니스 로직이나 유효성 검사 규칙을 포함하는 것을 고려합니다 (예: SQLAlchemy의 `@validates`).

## 결론

이 서비스 계층 표준화 가이드라인을 준수함으로써 우리는 코드베이스 전체의 일관성, 예측 가능성, 유지보수성 및 확장성을 크게 향상시킬 수 있습니다. 이는 팀원 간의 협업을 원활하게 하고, 새로운 기능 개발 및 기존 코드 변경 시 안정성을 높이는 데 기여할 것입니다. 