import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy import func, select
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

# 도메인 모델
from backend.partners.models import ApiKey, Partner
from backend.core.security import generate_api_key, get_password_hash, verify_password
from backend.core.exceptions import PartnerNotFoundError, APIKeyNotFoundError, AuthorizationError, NotFoundError, ConflictError, DatabaseError
from backend.db.database import get_db # Corrected import path
from backend.core import security # Corrected path

# 설정값 예시 (실제로는 설정 파일 등에서 관리)
API_KEY_EXPIRY_DAYS = 90
EXPIRY_NOTIFICATION_THRESHOLD_DAYS = 7

# 권한 상수 정의
PERMISSION_API_KEYS_CREATE = "api_keys.create"
PERMISSION_API_KEYS_DEACTIVATE = "api_keys.deactivate"
PERMISSION_API_KEYS_VIEW_ALL = "api_keys.view.all"
PERMISSION_API_KEYS_MANAGE_ALL = "api_keys.manage.all"

logger = logging.getLogger(__name__)

#---------------------------------------------------------------------------------------
# 유틸리티 함수
#---------------------------------------------------------------------------------------

def check_permission(permissions: List[str], required_permission: str) -> bool:
    """
    주어진 권한 목록에서 필요한 권한이 있는지 확인
    
    Args:
        permissions: 보유 권한 목록
        required_permission: 필요한 권한
        
    Returns:
        bool: 권한 보유 여부
    """
    if not permissions:
        return False
    
    # 정확히 일치하는 권한 확인
    if required_permission in permissions:
        return True
    
    # 와일드카드 권한 확인 (예: "api_keys.*")
    permission_parts = required_permission.split('.')
    for i in range(len(permission_parts)):
        wildcard_permission = '.'.join(permission_parts[:i]) + ".*"
        if wildcard_permission in permissions:
            return True
            
    return False

#---------------------------------------------------------------------------------------
# 파트너 저장소
#---------------------------------------------------------------------------------------

class PartnerRepository:
    """파트너 정보 관리를 위한 저장소 클래스"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_partner_by_id(self, partner_id: UUID) -> Optional[Partner]:
        """ID로 파트너 조회"""
        stmt = select(Partner).filter(Partner.id == partner_id)
        result = await self.db.execute(stmt)
        return result.scalars().first()
    
    async def get_active_partner_by_id(self, partner_id: UUID) -> Optional[Partner]:
        """ID로 활성 파트너만 조회"""
        stmt = select(Partner).filter(
            Partner.id == partner_id,
            Partner.is_active == True
        )
        result = await self.db.execute(stmt)
        partner = result.scalars().first()
        if not partner:
            logger.debug(f"Active partner not found for ID: {partner_id}")
        return partner
    
    async def create_partner(self, partner: Partner) -> Partner:
        """새 파트너 생성"""
        self.db.add(partner)
        await self.db.commit()
        await self.db.refresh(partner)
        return partner
    
    async def update_partner(self, partner_id: UUID, **kwargs) -> Partner:
        """파트너 정보 업데이트"""
        partner = await self.get_partner_by_id(partner_id)
        if not partner:
            raise PartnerNotFoundError(str(partner_id))
        
        # 업데이트할 필드만 설정
        for key, value in kwargs.items():
            if hasattr(partner, key):
                setattr(partner, key, value)
        
        await self.db.commit()
        await self.db.refresh(partner)
        return partner
    
    async def deactivate_partner(self, partner_id: UUID) -> bool:
        """파트너 비활성화 (소프트 삭제)"""
        partner = await self.get_partner_by_id(partner_id)
        if not partner:
            raise PartnerNotFoundError(str(partner_id))
        
        partner.is_active = False
        await self.db.commit()
        return True
    
    async def get_all_partners(self, include_inactive: bool = False) -> List[Partner]:
        """모든 파트너 목록 조회"""
        query = select(Partner)
        if not include_inactive:
            query = query.filter(Partner.is_active == True)
        
        result = await self.db.execute(query)
        return result.scalars().all()

#---------------------------------------------------------------------------------------
# API 키 서비스
#---------------------------------------------------------------------------------------

class APIKeyService:
    def __init__(self, db: AsyncSession, partner_repo: PartnerRepository):
        self.db = db
        self.partner_repo = partner_repo

    async def create_api_key(
        self,
        partner_id: UUID,
        name: str,
        requesting_partner_id: UUID,
        requesting_permissions: List[str],
        description: Optional[str] = None,
        permissions: Optional[List[str]] = None,
        created_by: Optional[str] = None # Usually requesting_partner_id
    ) -> tuple[ApiKey, str]:
        """새로운 API 키 생성 (권한 확인 및 만료일 포함)"""
        
        # --- Permission Check ---
        if partner_id != requesting_partner_id:
            # 다른 파트너의 API 키를 생성하려면 관리자 권한 필요
            has_admin_permission = check_permission(
                requesting_permissions,
                PERMISSION_API_KEYS_MANAGE_ALL
            )
            if not has_admin_permission:
                logger.warning(
                    f"Partner {requesting_partner_id} attempted to create API key for {partner_id} without permission."
                )
                raise AuthorizationError(
                    f"Missing required permission: {PERMISSION_API_KEYS_MANAGE_ALL}"
                )
        else:
            # 자신의 API 키를 생성하려면 생성 권한 필요
            has_create_permission = check_permission(
                requesting_permissions,
                PERMISSION_API_KEYS_CREATE
            )
            if not has_create_permission:
                logger.warning(
                    f"Partner {requesting_partner_id} attempted to create API key without create permission."
                )
                raise AuthorizationError(
                    f"Missing required permission: {PERMISSION_API_KEYS_CREATE}"
                )
        # --- End Permission Check ---

        # 대상 파트너 존재 확인 (활성 파트너여야 하는지 정책 결정 필요)
        target_partner = await self.partner_repo.get_partner_by_id(partner_id)
        if not target_partner:
            raise PartnerNotFoundError(str(partner_id))
        # if not target_partner.is_active:
        #     raise ValueError(f"Partner {partner_id} is inactive. Cannot create API key.")

        api_key_secret = generate_api_key() # 실제 클라이언트에게 전달될 시크릿
        hashed_key = get_password_hash(api_key_secret) # DB에 저장될 해시된 시크릿
        expires_at = datetime.now(timezone.utc) + timedelta(days=API_KEY_EXPIRY_DAYS)

        # 생성자 정보 설정
        creator_id = str(requesting_partner_id)

        db_api_key = ApiKey(
            partner_id=partner_id,
            hashed_key=hashed_key,
            name=name,
            description=description,
            permissions=permissions if permissions else [],
            expires_at=expires_at,
            created_by=creator_id # creator_id 필드가 모델에 있다고 가정
        )

        try:
            self.db.add(db_api_key)
            await self.db.commit()
            await self.db.refresh(db_api_key)
            # 생성된 키 객체와 실제 시크릿 반환 (시크릿은 이번에만 제공)
            logger.info(f"API Key {db_api_key.id} created for partner {partner_id} by {requesting_partner_id}")
            return db_api_key, api_key_secret
        except IntegrityError as e:
            await self.db.rollback()
            logger.exception(f"IntegrityError creating API key for partner {partner_id}: {e}")
            # 구체적인 제약 조건 위반 에러 처리 (예: UniqueViolation)
            raise ValueError("Failed to create API key due to data conflict.")
        except Exception as e:
            await self.db.rollback()
            logger.exception(f"Unexpected error creating API key for partner {partner_id}: {e}")
            raise

    async def deactivate_api_key(
        self,
        api_key_id: UUID,
        requesting_partner_id: UUID,
        requesting_permissions: List[str]
    ) -> bool:
        """API 키 비활성화 (권한 확인 추가)"""
        stmt = select(ApiKey).filter(ApiKey.id == api_key_id)
        result = await self.db.execute(stmt)
        api_key = result.scalars().first()

        if not api_key:
            raise APIKeyNotFoundError(str(api_key_id))

        # --- Permission Check ---
        if api_key.partner_id != requesting_partner_id:
            # 다른 파트너의 API 키를 비활성화하려면 관리자 권한 필요
            has_admin_permission = check_permission(
                requesting_permissions,
                PERMISSION_API_KEYS_MANAGE_ALL
            )
            if not has_admin_permission:
                 logger.warning(
                    f"Partner {requesting_partner_id} attempted to deactivate API key {api_key_id} belonging to {api_key.partner_id} without permission."
                 )
                 raise AuthorizationError(
                     f"Missing required permission: {PERMISSION_API_KEYS_MANAGE_ALL}"
                 )
        else:
            # 자신의 API 키를 비활성화하려면 비활성화 권한 필요
            # 또는 생성 권한이 있는 경우 자신의 키 비활성화 가능하게 할 수도 있음
            has_deactivate_permission = check_permission(
                requesting_permissions,
                PERMISSION_API_KEYS_DEACTIVATE
            ) or check_permission(
                requesting_permissions,
                PERMISSION_API_KEYS_CREATE # 자신의 키 생성 권한이 있다면 비활성화도 가능하게?
            )
            if not has_deactivate_permission:
                logger.warning(
                    f"Partner {requesting_partner_id} attempted to deactivate own API key {api_key_id} without permission."
                )
                raise AuthorizationError(
                    f"Missing required permission to deactivate key: {PERMISSION_API_KEYS_DEACTIVATE} or {PERMISSION_API_KEYS_CREATE}"
                )
        # --- End Permission Check ---

        if not api_key.is_active:
            logger.info(f"API Key {api_key_id} is already inactive.")
            return True # 이미 비활성화됨

        api_key.is_active = False
        try:
            await self.db.commit()
            await self.db.refresh(api_key) # 커밋 후 상태 갱신
            logger.info(f"API Key {api_key_id} deactivated by {requesting_partner_id}.")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.exception(f"Error deactivating API key {api_key_id}: {e}")
            # return False # 실패 시 예외를 발생시키는 것이 더 일반적
            raise Exception(f"Failed to deactivate API key {api_key_id}")

    async def rotate_api_key(
        self,
        api_key_id: UUID,
        requesting_partner_id: UUID,
        requesting_permissions: List[str]
    ) -> tuple[ApiKey, str]:
        """기존 API 키를 비활성화하고 새 키를 생성 (순환, 비동기, 권한 확인)"""
        # 1. 기존 키 조회 (권한 확인은 deactivate/create에서 수행)
        stmt = select(ApiKey).filter(ApiKey.id == api_key_id)
        result = await self.db.execute(stmt)
        current_key = result.scalars().first()

        if not current_key:
            raise APIKeyNotFoundError(str(api_key_id))

        # 2. 기존 키 비활성화 (내부적으로 권한 확인)
        # deactivate_api_key는 실패 시 예외를 발생시키므로 별도 확인 불필요
        await self.deactivate_api_key(
            api_key_id,
            requesting_partner_id,
            requesting_permissions
        )
        logger.info(f"Successfully deactivated old key {api_key_id} during rotation.")

        # 3. 새 키 생성 (내부적으로 권한 확인)
        try:
            new_key_name = f"{current_key.name} (Rotated {datetime.now(timezone.utc).strftime('%Y-%m-%d')})"
            new_key, new_secret = await self.create_api_key(
                partner_id=current_key.partner_id,
                name=new_key_name,
                requesting_partner_id=requesting_partner_id, # 요청자 ID 전달
                requesting_permissions=requesting_permissions, # 요청자 권한 전달
                description=current_key.description,
                permissions=current_key.permissions,
                created_by=str(requesting_partner_id) # 생성자 ID 명시
            )
            logger.info(f"API Key {api_key_id} successfully rotated to new key {new_key.id} by {requesting_partner_id}.")
            return new_key, new_secret
        except Exception as e:
             # 비활성화는 성공했지만 새 키 생성 실패 시 롤백?
             # 이미 비활성화 커밋되었을 수 있으므로 복잡. 로깅 중요.
             logger.exception(f"Failed to create new key during rotation for old key {api_key_id}. Old key remains deactivated.")
             # 적절한 예외 발생
             raise Exception(f"Failed to complete key rotation for {api_key_id}. Old key deactivated, new key creation failed.")

    async def get_expiring_keys(self, days_threshold: int = EXPIRY_NOTIFICATION_THRESHOLD_DAYS) -> List[ApiKey]:
        """지정된 일 수 내에 만료될 예정인 활성 API 키 목록 조회 (비동기)"""
        now = datetime.now(timezone.utc)
        expiry_limit = now + timedelta(days=days_threshold)

        stmt = select(ApiKey).filter(
            ApiKey.is_active == True,
            ApiKey.expires_at != None,
            ApiKey.expires_at > now, # 만료되지 않았고
            ApiKey.expires_at <= expiry_limit # 만료 임계일 안에 있는 키
        ).order_by(ApiKey.expires_at) # 만료일 순 정렬
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def record_api_key_usage(self, api_key_id: UUID, ip_address: Optional[str]):
        """API 키 사용 기록 업데이트 (마지막 사용 시간 및 IP, 비동기)"""
        # 성능을 위해 조건부 업데이트 또는 백그라운드 작업 고려
        try:
            # Optimistic update without select first (might be faster)
            # stmt = update(ApiKey).where(ApiKey.id == api_key_id).values(
            #     last_used_at=datetime.now(timezone.utc),
            #     last_used_ip=ip_address
            # ).execution_options(synchronize_session="fetch") # 또는 False
            # await self.db.execute(stmt)

            # Safer approach: select then update
            stmt = select(ApiKey).filter(ApiKey.id == api_key_id)
            result = await self.db.execute(stmt)
            api_key = result.scalars().first()

            if api_key:
                api_key.last_used_at = datetime.now(timezone.utc)
                if ip_address: # IP 주소가 있는 경우만 업데이트
                    api_key.last_used_ip = ip_address
                await self.db.commit()
            else:
                # 사용 기록을 남기려는 시점에 키가 삭제되었을 수 있음
                logger.warning(f"Attempted to record usage for non-existent API key {api_key_id}")

        except Exception as e:
            await self.db.rollback()
            logger.exception(f"Error recording usage for API key {api_key_id}: {e}")
            # 사용 기록 실패가 치명적이지 않다면 로깅 후 계속 진행

    async def get_keys_by_partner(
        self,
        partner_id: UUID,
        requesting_partner_id: UUID,
        requesting_permissions: List[str]
    ) -> List[ApiKey]:
        """특정 파트너의 모든 API 키 조회 (권한 확인 추가)"""
        # 권한 확인: 요청 대상 파트너가 자기 자신이거나, 전체 보기 권한(view.all) 또는 전체 관리 권한(manage.all)이 있는지 확인
        is_self = (partner_id == requesting_partner_id)
        can_view_all = check_permission(requesting_permissions, PERMISSION_API_KEYS_VIEW_ALL)
        can_manage_all = check_permission(requesting_permissions, PERMISSION_API_KEYS_MANAGE_ALL)

        if not (is_self or can_view_all or can_manage_all):
             logger.warning(f"Partner {requesting_partner_id} attempted to list keys for partner {partner_id} without sufficient permissions.")
             # 어떤 권한이 필요한지 명시
             raise AuthorizationError(f"Missing permission: requires self, {PERMISSION_API_KEYS_VIEW_ALL}, or {PERMISSION_API_KEYS_MANAGE_ALL} to view keys for partner {partner_id}")

        # 실제 조회 로직
        stmt = select(ApiKey).filter(ApiKey.partner_id == partner_id).order_by(ApiKey.created_at.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_api_key_owner(self, api_key_id: UUID) -> Optional[UUID]:
        """API 키 ID로 소유자 파트너 ID 조회"""
        stmt = select(ApiKey.partner_id).filter(ApiKey.id == api_key_id)
        result = await self.db.execute(stmt)
        owner_id = result.scalars().first()
        if not owner_id:
             logger.warning(f"Could not find owner for API key ID: {api_key_id}")
        return owner_id

#---------------------------------------------------------------------------------------
# 의존성 주입용 팩토리 함수
#---------------------------------------------------------------------------------------

def get_partner_repo(db: AsyncSession = Depends(get_db)) -> PartnerRepository:
    """PartnerRepository 인스턴스를 생성하여 반환"""
    return PartnerRepository(db=db)

def get_api_key_service(
    db: AsyncSession = Depends(get_db),
    partner_repo: PartnerRepository = Depends(get_partner_repo)
) -> APIKeyService:
    """APIKeyService 인스턴스를 생성하여 반환"""
    return APIKeyService(db=db, partner_repo=partner_repo)


#---------------------------------------------------------------------------------------
# 인증 의존성 함수
#---------------------------------------------------------------------------------------

async def get_current_api_key(
    request: Request,
    x_api_key_id: Optional[str] = Header(None, alias="X-API-Key-ID"),
    x_api_key_secret: Optional[str] = Header(None, alias="X-API-Key-Secret"),
    db: AsyncSession = Depends(get_db), # DB 세션 주입
    api_key_service: APIKeyService = Depends(get_api_key_service) # 서비스 주입
) -> ApiKey:
    """
    요청 헤더에서 API 키 ID와 시크릿을 읽어 인증하고, 유효한 APIKey 객체를 반환합니다.
    인증 실패 시 HTTPException(401) 발생.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key credentials",
        headers={"WWW-Authenticate": "API Key"}, # 인증 방식 명시
    )

    if not x_api_key_id or not x_api_key_secret:
        logger.debug("Missing X-API-Key-ID or X-API-Key-Secret header")
        raise credentials_exception

    try:
        key_id = UUID(x_api_key_id)
    except ValueError:
        logger.debug(f"Invalid API Key ID format: {x_api_key_id}")
        raise credentials_exception

    # DB에서 API 키 조회
    stmt = select(ApiKey).filter(ApiKey.id == key_id)
    result = await db.execute(stmt)
    api_key: Optional[ApiKey] = result.scalars().first()

    if not api_key:
        logger.warning(f"API Key not found for ID: {key_id}")
        raise credentials_exception

    # 키 상태 확인 (활성, 만료)
    now = datetime.now(timezone.utc)
    if not api_key.is_active:
        logger.warning(f"Attempt to use inactive API Key: {key_id}")
        raise credentials_exception
    if api_key.expires_at and api_key.expires_at <= now:
        logger.warning(f"Attempt to use expired API Key: {key_id} (Expired at: {api_key.expires_at})")
        raise credentials_exception

    # 비밀번호(시크릿) 검증
    if not verify_password(x_api_key_secret, api_key.hashed_key):
        logger.warning(f"Invalid secret provided for API Key: {key_id}")
        # 실패 시 사용 기록? 보안상 고려 필요
        raise credentials_exception

    # 인증 성공, 사용 기록 업데이트 (백그라운드 작업 고려)
    client_ip = request.client.host if request.client else None
    # await api_key_service.record_api_key_usage(api_key_id=api_key.id, ip_address=client_ip)
    # 주의: record_api_key_usage 내부에서 commit 발생. 동시성 문제 가능성.
    #      별도 트랜잭션 또는 비동기 작업으로 분리하는 것이 안전할 수 있음.
    #      일단 여기서는 호출하지 않고, 필요 시 미들웨어 등에서 처리 고려.
    #      혹은 record_api_key_usage에서 commit을 제거하고 호출 후 별도 commit?

    logger.debug(f"API Key authenticated successfully: {key_id}")
    return api_key

async def get_current_partner(
    api_key: ApiKey = Depends(get_current_api_key),
    partner_repo: PartnerRepository = Depends(get_partner_repo)
) -> Partner:
    """
    인증된 API 키를 사용하여 현재 요청을 보낸 활성 파트너 정보를 가져옵니다.
    파트너 조회 실패 시 HTTPException(401) 발생.
    """
    partner = await partner_repo.get_active_partner_by_id(api_key.partner_id)
    if not partner:
        # API 키는 유효하나 연결된 파트너가 없거나 비활성화된 경우
        logger.error(f"Authenticated API key {api_key.id} belongs to inactive or non-existent partner {api_key.partner_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Associated partner is inactive or not found",
            headers={"WWW-Authenticate": "API Key"},
        )
    logger.debug(f"Current partner identified: {partner.id} ({partner.name})")
    return partner

async def get_current_permissions(
    api_key: ApiKey = Depends(get_current_api_key)
) -> List[str]:
    """현재 인증된 API 키에 부여된 권한 목록을 반환합니다."""
    return api_key.permissions if api_key.permissions else []

#---------------------------------------------------------------------------------------
# API 라우터
#---------------------------------------------------------------------------------------

router = APIRouter(
    prefix="/auth", # 라우터 경로 접두사 추가 (예시)
    tags=["API Keys"], # API 문서 그룹화
)

@router.post(
    "/api-keys",
    status_code=status.HTTP_201_CREATED,
    response_model=Dict[str, str] # 응답 모델 명시
)
async def create_partner_api_key( # 함수 이름 명확화
    partner_id: UUID, # 경로 파라미터 대신 요청 본문 또는 쿼리로 받는 것이 일반적일 수 있음
    name: str, # 요청 본문으로 받을 정보들 (스키마 필요)
    description: Optional[str] = None,
    permissions: Optional[List[str]] = None,
    # --- 인증 및 권한 정보 ---
    current_partner: Partner = Depends(get_current_partner),
    current_permissions: List[str] = Depends(get_current_permissions),
    # --- 서비스 의존성 ---
    api_key_service: APIKeyService = Depends(get_api_key_service)
):
    """
    지정된 파트너를 위한 새로운 API 키를 생성합니다.

    - 요청자는 자신의 파트너 ID 또는 다른 파트너 ID에 대해 키를 생성할 수 있습니다.
    - 다른 파트너의 키를 생성하려면 `api_keys.manage.all` 권한이 필요합니다.
    - 자신의 키를 생성하려면 `api_keys.create` 권한이 필요합니다.
    - 생성된 키의 ID와 시크릿 값을 반환합니다. 시크릿 값은 이 응답에서만 확인할 수 있습니다.
    """
    # Pydantic 모델을 사용하여 요청 본문 유효성 검사 및 데이터 수신 권장
    # 예: CreateAPIKeyRequest(name: str, description: Optional[str], permissions: Optional[List[str]])
    
    api_key, secret = await api_key_service.create_api_key(
        partner_id=partner_id,
        name=name,
        description=description,
        permissions=permissions,
        requesting_partner_id=current_partner.id, # 요청 파트너 ID
        requesting_permissions=current_permissions, # 요청 파트너 권한
        created_by=str(current_partner.id) # 생성자 명시
    )
    # 생성된 키의 ID와 시크릿 반환
    return {"id": str(api_key.id), "secret": secret}

@router.delete(
    "/api-keys/{api_key_id}",
    status_code=status.HTTP_204_NO_CONTENT # 성공 시 내용 없음
)
async def deactivate_partner_api_key( # 함수 이름 명확화
    api_key_id: UUID,
    current_partner: Partner = Depends(get_current_partner),
    current_permissions: List[str] = Depends(get_current_permissions),
    api_key_service: APIKeyService = Depends(get_api_key_service)
):
    """
    지정된 API 키를 비활성화합니다.

    - 요청자는 자신의 API 키 또는 다른 파트너의 API 키를 비활성화할 수 있습니다.
    - 다른 파트너의 키를 비활성화하려면 `api_keys.manage.all` 권한이 필요합니다.
    - 자신의 키를 비활성화하려면 `api_keys.deactivate` 또는 `api_keys.create` 권한이 필요합니다.
    """
    await api_key_service.deactivate_api_key(
        api_key_id=api_key_id,
        requesting_partner_id=current_partner.id,
        requesting_permissions=current_permissions
    )
    # 성공 시 204 No Content 반환 (FastAPI가 자동으로 처리)
    return None # 명시적으로 None 반환 가능

@router.post(
    "/api-keys/{api_key_id}/rotate",
    response_model=Dict[str, str]
)
async def rotate_partner_api_key( # 함수 이름 명확화
    api_key_id: UUID,
    current_partner: Partner = Depends(get_current_partner),
    current_permissions: List[str] = Depends(get_current_permissions),
    api_key_service: APIKeyService = Depends(get_api_key_service)
):
    """
    지정된 API 키를 순환(rotate)합니다.
    기존 키는 비활성화되고, 동일한 속성을 가진 새로운 키가 생성되어 반환됩니다.

    - 순환 권한은 비활성화 및 생성 권한 검사를 따릅니다.
    - 새로운 키의 ID와 시크릿 값을 반환합니다. 시크릿 값은 이 응답에서만 확인할 수 있습니다.
    """
    new_key, new_secret = await api_key_service.rotate_api_key(
        api_key_id=api_key_id,
        requesting_partner_id=current_partner.id,
        requesting_permissions=current_permissions
    )
    return {"id": str(new_key.id), "secret": new_secret}

@router.get(
    "/partners/{partner_id}/api-keys",
    response_model=List[Dict[str, Any]] # 응답 모델 구체화 (Pydantic 모델 권장)
)
async def get_partner_api_keys(
    partner_id: UUID,
    current_partner: Partner = Depends(get_current_partner),
    current_permissions: List[str] = Depends(get_current_permissions),
    api_key_service: APIKeyService = Depends(get_api_key_service)
):
    """
    특정 파트너의 모든 API 키 목록을 조회합니다.

    - 자신의 API 키 목록을 조회할 수 있습니다.
    - 다른 파트너의 키 목록을 조회하려면 `api_keys.view.all` 또는 `api_keys.manage.all` 권한이 필요합니다.
    - 응답에는 API 키의 시크릿 값은 포함되지 않습니다.
    """
    keys = await api_key_service.get_keys_by_partner(
        partner_id=partner_id,
        requesting_partner_id=current_partner.id,
        requesting_permissions=current_permissions
    )
    # 응답 데이터 형식 정의 (Pydantic 모델 사용 권장)
    # 예: APIKeyInfo(id: UUID, name: str, ...)
    return [
        {
            "id": str(key.id),
            "name": key.name,
            "description": key.description,
            "permissions": key.permissions,
            "created_at": key.created_at,
            "expires_at": key.expires_at,
            "is_active": key.is_active,
            "last_used_at": key.last_used_at,
            "last_used_ip": key.last_used_ip, # 마지막 사용 IP 추가
            "created_by": key.created_by # 생성자 정보 추가 (모델에 필드 필요)
        }
        for key in keys
    ]