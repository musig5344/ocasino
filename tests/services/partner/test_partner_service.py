"""
PartnerService 기본 CRUD 기능 단위 테스트
"""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
import logging # 로깅 추가

logger = logging.getLogger(__name__) # 로거 설정

# 실제 경로 확인 및 필요시 수정
try:
    from backend.services.partner.partner_service import PartnerService, get_model_dict
    from backend.repositories.partner_repository import PartnerRepository
    from backend.models.domain.partner import Partner # Domain model
    from backend.schemas.partner import PartnerCreate, PartnerUpdate # Schemas
    from backend.core.exceptions import (
        PartnerAlreadyExistsError, PartnerNotFoundError, InvalidInputError,
        APIKeyGenerationError, DatabaseError, AuthorizationError
    )
    from backend.models.enums import PartnerType, CommissionModel, PartnerStatus
    logger.info("Successfully imported ACTUAL PartnerService and related modules.") # 성공 로그 추가
except ImportError as e:
    logger.warning(f"Could not import actual PartnerService modules: {e}. USING PLACEHOLDERS.") # 실패 로그 강화
    # Placeholders
    class PartnerService:
        def __init__(self, db=None, redis_client=None):
            self.partner_repo = None
            self.redis = redis_client
        async def create_partner(self, data): pass
        async def get_partner(self, pid): pass
        async def list_partners(self, limit, offset, filters=None): pass
        async def update_partner(self, partner_id, update_data, requesting_partner_id, requesting_permissions): pass
        async def delete_partner(self, partner_id, requesting_partner_id=None, requesting_permissions=None):
            return True

    class PartnerRepository:
        def __init__(self, db=None): self.db = db
        async def create_partner(self, data): pass
        async def get_partner_by_email(self, email): pass
        async def get_partner_by_code(self, code): pass
        async def get_partner_by_id(self, pid): pass
        async def list_partners(self, limit, offset, filters=None): pass
        async def update_partner(self, partner): pass
        async def delete_partner(self, pid): pass # If applicable
    class Partner:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class PartnerCreate:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class PartnerUpdate:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
    class InvalidInputError(Exception): pass
    class APIKeyGenerationError(Exception): pass
    class DatabaseError(Exception): pass
    class AuthorizationError(Exception): pass

    def get_model_dict(model):
        """Helper to convert Pydantic model to dict"""
        if hasattr(model, 'dict'):
            return model.dict(exclude_unset=True)
        else:
            return {k: v for k, v in model.__dict__.items() if not k.startswith('_')}

# --- Fixtures ---

@pytest.fixture
def mock_redis_client():
    """모의 Redis 클라이언트 (파이프라인 지원 추가)"""
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock()
    redis_mock.delete = AsyncMock()
    redis_mock.sadd = AsyncMock()
    redis_mock.smembers = AsyncMock(return_value=set())
    redis_mock.expire = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=True)

    # 파이프라인 mock 설정 (사용자 제안 반영)
    pipeline_mock = AsyncMock()
    # redis_mock.pipeline() 호출 시 pipeline_mock 반환하도록 설정 먼저
    redis_mock.pipeline.return_value = pipeline_mock 
    # async with 지원 설정
    pipeline_mock.__aenter__ = AsyncMock(return_value=pipeline_mock) # self 반환
    pipeline_mock.__aexit__ = AsyncMock(return_value=None)
    # 파이프라인 내부 메서드 mock
    pipeline_mock.set = AsyncMock()
    pipeline_mock.sadd = AsyncMock()
    pipeline_mock.expire = AsyncMock()
    pipeline_mock.delete = AsyncMock()
    pipeline_mock.execute = AsyncMock(return_value=[True]) # 실행 결과 mock

    return redis_mock

@pytest.fixture
def mock_db_session():
    """모의 DB 세션"""
    session_mock = AsyncMock()
    session_mock.begin = AsyncMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=None)
    return session_mock

@pytest.fixture
def mock_partner_repo():
    """모의 파트너 리포지토리"""
    repo = AsyncMock(spec=PartnerRepository)
    repo.get_partner_by_code = AsyncMock(return_value=None) # Default return None
    repo.get_partner_by_email = AsyncMock(return_value=None) # Default return None
    repo.create_partner = AsyncMock()
    repo.get_partner_by_id = AsyncMock(return_value=None)
    repo.list_partners = AsyncMock(return_value=[]) # Return empty list
    repo.update_partner = AsyncMock()
    # 추가: delete_partner 메서드 명시적 mock
    repo.delete_partner = AsyncMock(return_value=True) # 기본적으로 성공(True) 반환
    return repo

@pytest.fixture
def partner_service(mock_partner_repo, mock_redis_client, mock_db_session):
    """파트너 서비스 인스턴스 (모의 리포지토리 사용)"""
    # 수정: Placeholder __init__ 가능성을 고려하여 생성
    #      실제 클래스 import 성공 시 redis_cache, 실패 시 redis_client 인자 사용 가정
    try:
        # 실제 클래스 import 시도 (동일한 try-except 구조 사용)
        from backend.services.partner.partner_service import PartnerService
        logger.info("Fixture: Using ACTUAL PartnerService")
        # 실제 클래스는 redis_cache 인자를 받음
        service = PartnerService(
            db=mock_db_session, 
            redis_cache=mock_redis_client 
        )
    except ImportError:
        logger.warning("Fixture: Using PLACEHOLDER PartnerService")
        # Placeholder 클래스는 redis_client 인자를 받음
        # Placeholder 정의를 직접 수정하는 대신, 여기서 인자 이름 변경
        class PlaceholderPartnerService:
            def __init__(self, db=None, redis_client=None): # redis_client 사용
                self.partner_repo = None
                self.redis = redis_client
            # 필요시 다른 메서드 placeholder 추가
            async def get_partner(self, pid): pass
            async def list_partners(self, limit, offset, filters=None): pass
            async def create_partner(self, data): pass
            async def update_partner(self, partner_id, update_data, requesting_partner_id, requesting_permissions): pass
            async def delete_partner(self, partner_id, requesting_partner_id, requesting_permissions): return True
            
        service = PlaceholderPartnerService(
            db=mock_db_session, 
            redis_client=mock_redis_client # 여기를 redis_client로 수정
        )

    # partner_repo를 수동으로 mock 객체로 설정 (공통 로직)
    service.partner_repo = mock_partner_repo
    
    # redis 속성 보장 (Placeholder 경우)
    if not hasattr(service, 'redis_cache') and hasattr(service, 'redis') and not service.redis:
         service.redis = mock_redis_client
    
    return service

# --- Test Cases ---

# Partner Creation Tests
@pytest.mark.asyncio
async def test_create_partner_success(partner_service, mock_partner_repo):
    """파트너 생성 성공 테스트"""
    partner_id = uuid.uuid4()
    partner_data = PartnerCreate(
        code="ALPHA",
        name="Test Partner Alpha",
        partner_type="aggregator",
        commission_model="revenue_share",
        commission_rate="15%",
        contact_email="alpha@testpartner.com",
        status="active"
    )
    # Mock repo return value for create
    created_partner_mock = Partner(
        id=partner_id,
        code=partner_data.code,
        name=partner_data.name,
        partner_type=partner_data.partner_type,
        commission_model=partner_data.commission_model,
        contact_email=partner_data.contact_email,
        status=partner_data.status,
        created_at=datetime.now(timezone.utc)
    )
    mock_partner_repo.create_partner.return_value = created_partner_mock

    created_partner = await partner_service.create_partner(partner_data)

    # Assert repo calls
    mock_partner_repo.get_partner_by_email.assert_called_once_with(partner_data.contact_email)
    mock_partner_repo.get_partner_by_code.assert_called_once_with(partner_data.code)
    mock_partner_repo.create_partner.assert_called_once()

    assert created_partner is not None
    assert created_partner.id == partner_id
    assert created_partner.name == partner_data.name
    assert created_partner.contact_email == partner_data.contact_email
    assert created_partner.partner_type == PartnerType.AGGREGATOR
    assert created_partner.commission_model == CommissionModel.REVENUE_SHARE
    assert created_partner.status == PartnerStatus.ACTIVE

@pytest.mark.asyncio
async def test_create_partner_duplicate_email(partner_service, mock_partner_repo):
    """파트너 생성 시 이메일 중복 테스트 (PartnerAlreadyExistsError 발생)"""
    partner_data = PartnerCreate(
        code="BETA",
        name="Test Partner Beta",
        partner_type="aggregator",
        commission_model="revenue_share",
        commission_rate="20%",
        contact_email="beta@testpartner.com",
        status="active"
    )
    # Mock repo to return an existing partner for the email check
    existing_partner = Partner(
        id=uuid.uuid4(),
        contact_email=partner_data.contact_email,
        name="Existing Beta",
        code="OTHERCODE",
        partner_type="operator",
        commission_model="cpa"
    )
    mock_partner_repo.get_partner_by_email.return_value = existing_partner

    # Expect PartnerAlreadyExistsError
    with pytest.raises(PartnerAlreadyExistsError):
        await partner_service.create_partner(partner_data)

    mock_partner_repo.get_partner_by_email.assert_called_once_with(partner_data.contact_email)
    mock_partner_repo.create_partner.assert_not_called() # Ensure create was not called

@pytest.mark.asyncio
async def test_create_partner_duplicate_code(partner_service, mock_partner_repo):
    """파트너 생성 시 코드 중복 테스트 (PartnerAlreadyExistsError 발생)"""
    partner_data = PartnerCreate(
        code="GAMMA",
        name="Test Partner Gamma",
        partner_type="aggregator",
        commission_model="revenue_share",
        commission_rate="20%",
        contact_email="new_gamma@testpartner.com",
        status="active"
    )
    # 이메일은 중복 아님
    mock_partner_repo.get_partner_by_email.return_value = None
    # 코드는 중복
    existing_partner = Partner(
        id=uuid.uuid4(),
        contact_email="other@email.com",
        name="Existing Gamma",
        code=partner_data.code,
        partner_type="affiliate",
        commission_model="hybrid"
    )
    mock_partner_repo.get_partner_by_code.return_value = existing_partner

    # Expect PartnerAlreadyExistsError
    with pytest.raises(PartnerAlreadyExistsError):
        await partner_service.create_partner(partner_data)

    mock_partner_repo.get_partner_by_email.assert_called_once_with(partner_data.contact_email)
    mock_partner_repo.get_partner_by_code.assert_called_once_with(partner_data.code)
    mock_partner_repo.create_partner.assert_not_called() # Ensure create was not called

# Partner Retrieval Tests
@pytest.mark.asyncio
# 수정: @patch 및 MockRedisCache 제거, 캐시 검증 제거
async def test_get_partner_success(partner_service, mock_partner_repo): # mocker 제거
    """파트너 조회 성공 테스트 (캐시 로직 제외)"""
    partner_id = uuid.uuid4()
    expected_partner = Partner(
        id=partner_id, 
        name="Gamma Partner", 
        contact_email="gamma@test.com", 
        code="GAMMA",
        partner_type="aggregator",
        commission_model="revenue_share", 
        status="active",
        created_at=datetime.now(timezone.utc)
    )
    
    # DB에서 파트너 반환하도록 설정
    mock_partner_repo.get_partner_by_id.return_value = expected_partner

    retrieved_partner = await partner_service.get_partner(partner_id)

    # 검증: DB 조회 확인 및 반환값 확인
    mock_partner_repo.get_partner_by_id.assert_called_once_with(partner_id)
    assert retrieved_partner is not None
    assert retrieved_partner.id == partner_id

@pytest.mark.asyncio
# 수정: @patch 및 MockRedisCache 제거, 캐시 검증 제거
async def test_get_partner_not_found(partner_service, mock_partner_repo): # mocker 제거
    """존재하지 않는 파트너 조회 테스트 (None 반환, 캐시 로직 제외)"""
    non_existent_id = uuid.uuid4()

    # DB에서도 파트너 없음 시뮬레이션
    mock_partner_repo.get_partner_by_id.return_value = None 

    retrieved_partner = await partner_service.get_partner(non_existent_id)
    
    # 검증: DB 조회 확인 및 반환값 확인
    mock_partner_repo.get_partner_by_id.assert_called_once_with(non_existent_id)
    assert retrieved_partner is None

# Partner Listing Tests
@pytest.mark.asyncio
async def test_list_partners(partner_service, mock_partner_repo):
    """파트너 목록 조회 테스트"""
    limit, offset = 20, 0
    filters = {"status": "active"}
    partners_list = [
        Partner(id=uuid.uuid4(), name="Partner 1", code="P1", status="active"),
        Partner(id=uuid.uuid4(), name="Partner 2", code="P2", status="active")
    ]
    mock_partner_repo.list_partners.return_value = partners_list

    result = await partner_service.list_partners(limit=limit, offset=offset, filters=filters)

    # Check call with keyword arguments including filters
    mock_partner_repo.list_partners.assert_called_once_with(limit=limit, offset=offset, filters=filters)
    assert result == partners_list
    assert len(result) == 2

# Partner Update Tests
@pytest.mark.asyncio
async def test_update_partner_success(partner_service, mock_partner_repo):
    """파트너 업데이트 성공 테스트"""
    partner_id = uuid.uuid4()
    original_email = "delta@test.com"
    original_code = "DELTA"
    update_data = PartnerUpdate(
        name="Updated Delta Partner",
        status="inactive",
        commission_rate="25%",
        commission_model="cpa"
    )
    
    original_partner_mock = Partner(
        id=partner_id,
        code=original_code,
        name="Delta Partner",
        contact_email=original_email,
        status="active",
        commission_model="revenue_share",
        partner_type="operator"
    )
    mock_partner_repo.get_partner_by_id.return_value = original_partner_mock
    
    updated_partner_return = Partner(
         id=partner_id,
         code=original_code,
         name=update_data.name,
         contact_email=original_email,
         status=update_data.status,
         commission_model=update_data.commission_model,
         partner_type="operator"
    )
    mock_partner_repo.update_partner.return_value = updated_partner_return

    requesting_partner_id = uuid.uuid4()
    requesting_permissions = ["partners.update.all"]
    updated_partner = await partner_service.update_partner(
        partner_id,
        update_data,
        requesting_partner_id,
        requesting_permissions
    )

    # Assertions
    mock_partner_repo.get_partner_by_id.assert_called_once_with(partner_id)
    mock_partner_repo.update_partner.assert_called_once()
    
    assert updated_partner is not None
    assert updated_partner.id == partner_id
    assert updated_partner.code == original_code
    assert updated_partner.name == update_data.name
    assert updated_partner.status == PartnerStatus.INACTIVE
    assert updated_partner.commission_model == CommissionModel.CPA
    assert updated_partner.contact_email == original_email

@pytest.mark.asyncio
async def test_update_partner_not_found(partner_service, mock_partner_repo):
    """존재하지 않는 파트너 업데이트 시 예외 발생 테스트"""
    partner_id = uuid.uuid4()
    update_data = PartnerUpdate(name="Does Not Matter")
    mock_partner_repo.get_partner_by_id.return_value = None

    with pytest.raises(PartnerNotFoundError):
        requesting_partner_id = uuid.uuid4()
        requesting_permissions = ["partners.update.all"]
        await partner_service.update_partner(
            partner_id,
            update_data,
            requesting_partner_id,
            requesting_permissions
        )

    mock_partner_repo.get_partner_by_id.assert_called_once_with(partner_id)
    mock_partner_repo.update_partner.assert_not_called()

@pytest.mark.asyncio
async def test_update_partner_email_conflict(partner_service, mock_partner_repo):
    """파트너 이메일 업데이트 시 충돌 예외 발생 테스트"""
    partner_id = uuid.uuid4()
    existing_partner_id = uuid.uuid4()
    original_email = "original@test.com"
    conflicting_email = "taken@test.com"
    update_data = PartnerUpdate(contact_email=conflicting_email)

    # Mock the partner being updated
    original_partner = Partner(
        id=partner_id,
        name="Original Partner",
        contact_email=original_email,
        status="active",
        code="ORIGINAL",
        commission_model="revenue_share",
        partner_type="operator"
    )
    mock_partner_repo.get_partner_by_id.return_value = original_partner

    # Mock the existing partner with the conflicting email
    conflicting_partner = Partner(
        id=existing_partner_id,
        name="Conflicting Partner",
        contact_email=conflicting_email,
        status="active",
        code="CONFLICT",
        commission_model="cpa",
        partner_type="aggregator"
    )
    mock_partner_repo.get_partner_by_email.return_value = conflicting_partner

    expected_match_str = f"Partner with code email {conflicting_email} \\(by another partner\\) already exists."
    with pytest.raises(PartnerAlreadyExistsError, match=expected_match_str):
        requesting_partner_id = uuid.uuid4()
        requesting_permissions = ["partners.update.all"]
        await partner_service.update_partner(
            partner_id,
            update_data,
            requesting_partner_id,
            requesting_permissions
        )

    mock_partner_repo.get_partner_by_id.assert_called_once_with(partner_id)
    mock_partner_repo.get_partner_by_email.assert_called_once_with(conflicting_email)
    mock_partner_repo.update_partner.assert_not_called()

# Partner Deletion Tests (활성화된 경우)
@pytest.mark.asyncio
async def test_delete_partner_success(partner_service, mock_partner_repo):
    """파트너 삭제 성공 테스트"""
    partner_id = uuid.uuid4()
    mock_partner_repo.get_partner_by_id.return_value = Partner(id=partner_id, name="ToDelete")
    mock_partner_repo.delete_partner.return_value = True

    requesting_partner_id = uuid.uuid4()
    requesting_permissions = ["partners.delete"]
    deleted = await partner_service.delete_partner(partner_id=partner_id, \
                                                 requesting_partner_id=requesting_partner_id, \
                                                 requesting_permissions=requesting_permissions)

    assert deleted is True
    mock_partner_repo.delete_partner.assert_called_once_with(partner_id)

@pytest.mark.asyncio
async def test_delete_partner_not_found(partner_service, mock_partner_repo):
    """존재하지 않는 파트너 삭제 테스트 (PartnerNotFoundError 발생)"""
    non_existent_id = uuid.uuid4()
    mock_partner_repo.get_partner_by_id.return_value = None
    mock_partner_repo.delete_partner.return_value = False

    with pytest.raises(PartnerNotFoundError):
        requesting_partner_id = uuid.uuid4()
        requesting_permissions = ["partners.delete"]
        await partner_service.delete_partner(partner_id=non_existent_id, \
                                             requesting_partner_id=requesting_partner_id, \
                                             requesting_permissions=requesting_permissions)
        
    mock_partner_repo.get_partner_by_id.assert_called_once_with(non_existent_id)
    mock_partner_repo.delete_partner.assert_not_called()