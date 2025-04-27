"""
인증 서비스
API 키 인증, 권한 관리 등 비즈니스 로직 담당
"""
import logging
from uuid import UUID
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta, timezone
import ipaddress

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status, Request
from redis.asyncio import Redis

from backend.partners.models import Partner, PartnerStatus, ApiKey
from backend.partners.repository import PartnerRepository
from backend.partners.service import PartnerService
from backend.core.security import get_password_hash, verify_password, create_access_token, verify_access_token
from backend.core.config import settings
from backend.core.exceptions import AuthenticationError, AuthorizationError, InvalidCredentialsError, NotAllowedIPError, PermissionDeniedError
from backend.cache.redis_cache import get_redis_client
from backend.schemas.auth import TokenResponse, LoginRequest
from backend.utils.permissions import check_permission

logger = logging.getLogger(__name__)

class AuthService:
    """인증 서비스"""
    
    def __init__(self, db: AsyncSession, redis_client: Redis):
        self.db = db
        self.partner_repo = PartnerRepository(db)
        self.partner_service = PartnerService(db)
        self.redis = redis_client
    
    async def authenticate_api_key(self, api_key: str) -> Tuple[ApiKey, Partner]:
        """
        API 키 인증
        
        Args:
            api_key: API 키
            
        Returns:
            Tuple[ApiKey, Partner]: API 키 및 파트너 객체
            
        Raises:
            AuthenticationError: 인증 실패 시
        """
        # Calculate hash once
        hashed_key = get_password_hash(api_key)
        cache_key = f"api_key:{hashed_key}"
        cached_data = await self.redis.get(cache_key)

        api_key_obj: Optional[ApiKey] = None
        partner: Optional[Partner] = None

        if cached_data:
            try:
                # --- 수정: 캐시 값(bytes)을 디코드하고 UUID로 변환 --- #
                api_key_id = UUID(cached_data.decode('utf-8'))
                # -------------------------------------------------- #
                api_key_obj = await self.partner_repo.get_api_key_by_id(api_key_id)
                if api_key_obj:
                    partner = await self.partner_repo.get_partner_by_id(api_key_obj.partner_id)

            except Exception as e:
                # Log cache parsing error
                print(f"Cache error: {e}") # Replace with proper logging
                await self.redis.delete(cache_key)

        if not api_key_obj or not partner:
            # Cache miss or invalid cache data, lookup in DB by hashed key
            api_key_obj = await self.partner_repo.get_active_api_key_by_hash(hashed_key)
            if not api_key_obj:
                raise AuthenticationError("Invalid or inactive API key")
            partner = await self.partner_repo.get_partner_by_id(api_key_obj.partner_id)
            if not partner:
                 # This case should ideally not happen if DB constraints are correct
                 raise AuthenticationError("Partner associated with API key not found")
            # Optionally, update cache here if cache miss
            # Use a simple cache value like the api_key_id string for this example
            cache_value = str(api_key_obj.id) 
            await self.redis.set(cache_key, cache_value, ex=3600) # Cache for 1 hour

        # --- Common Checks for both cache hit (DB verified) and cache miss ---

        # Check if API key is active (redundant if get_active_api_key* methods are used, but safe) 
        if not api_key_obj.is_active:
             raise AuthenticationError("API key is inactive")

        # Expiry check
        if api_key_obj.expires_at:
            # Ensure both are timezone-aware (UTC)
            now_utc = datetime.now(timezone.utc)
            expires_at = api_key_obj.expires_at
            # If expires_at is naive, assume UTC
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            
            if expires_at <= now_utc:
                 raise AuthenticationError("API key has expired")

        # Partner status check (Modified as requested)
        if partner.status != PartnerStatus.ACTIVE and partner.status != "active":
            # Handles both Enum and potential string values during transition/testing
            raise AuthenticationError(f"Partner is not active (status: {partner.status})")

        # IP Whitelist check (assuming it's done here or in middleware)
        # Example: await self.verify_ip_whitelist(partner.id, request_ip) # Needs request_ip

        # Update last used time (consider doing this less frequently)
        current_time = datetime.utcnow()
        # Check if last_used_at is None or older than 1 hour
        if api_key_obj.last_used_at is None or \
           (isinstance(api_key_obj.last_used_at, datetime) and (current_time - api_key_obj.last_used_at) > timedelta(hours=1)) or \
           not isinstance(api_key_obj.last_used_at, datetime): # Handle potential non-datetime values
             try:
                 api_key_obj.last_used_at = current_time
                 # Use the session associated with the partner_repo for flushing
                 await self.partner_repo.db_session.flush([api_key_obj]) # Flush specific object
             except Exception as e:
                  print(f"Error updating API key last_used_at: {e}") # Log error
                  # Decide if this error should prevent authentication

        return api_key_obj, partner
    
    async def verify_ip_whitelist(self, partner_id: UUID, client_ip: str) -> bool:
        """
        IP 화이트리스트 검증
        
        Args:
            partner_id: 파트너 ID
            client_ip: 클라이언트 IP
            
        Returns:
            bool: 허용 여부
            
        Raises:
            NotAllowedIPError: 허용되지 않은 IP 접근 시
        """
        # 파트너의 허용 IP 목록 조회
        allowed_ips = await self.partner_repo.get_allowed_ips(partner_id)
        
        # IP 화이트리스트가 없으면 모든 IP 허용
        if not allowed_ips:
            return True
        
        # IP 주소 객체 생성
        try:
            client_ip_obj = ipaddress.ip_address(client_ip)
        except ValueError:
            logger.warning(f"Invalid IP address format: {client_ip}")
            raise NotAllowedIPError("Invalid IP address format")
        
        # 허용 IP/네트워크 확인
        for ip in allowed_ips:
            # CIDR 형식인지 확인
            if "/" in ip.ip_address:
                # 네트워크 범위 확인
                try:
                    network = ipaddress.ip_network(ip.ip_address, strict=False)
                    if client_ip_obj in network:
                        return True
                except ValueError:
                    logger.warning(f"Invalid IP network format: {ip.ip_address}")
                    continue
            else:
                # 단일 IP 비교
                if ip.ip_address == client_ip:
                    return True
        
        # 허용된 IP가 없음
        raise NotAllowedIPError(f"IP {client_ip} not in whitelist for partner {partner_id}")
    
    async def check_permission(self, api_key: ApiKey, required_permission: str) -> bool:
        """
        권한 확인
        
        Args:
            api_key: API 키 객체
            required_permission: 필요한 권한
            
        Returns:
            bool: 권한 보유 여부
            
        Raises:
            PermissionDeniedError: 권한이 없는 경우
        """
        # 모든 권한 확인 (* 와일드카드)
        if "*" in api_key.permissions:
            return True
        
        # 특정 리소스의 모든 권한 확인 (wallet:* 등)
        resource = required_permission.split(":")[0]
        if f"{resource}:*" in api_key.permissions:
            return True
        
        # 특정 권한 확인
        if required_permission in api_key.permissions:
            return True
        
        # 권한 없음
        raise PermissionDeniedError(f"Missing required permission: {required_permission}")

    async def authenticate_request(self, request: Request, required_permission: Optional[str] = None) -> Tuple[ApiKey, Partner]:
        """
        FastAPI 요청 객체에서 API 키를 추출하고 인증 및 권한 부여 수행
        """
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            logger.warning("API key missing in request headers")
            raise HTTPException(status_code=401, detail="API key required")

        try:
            # API 키 인증 (await 추가)
            api_key_obj, partner = await self.authenticate_api_key(api_key)

            # IP 화이트리스트 검증 (await 추가)
            client_ip = request.client.host
            await self.verify_ip_whitelist(partner.id, client_ip)

            # 권한 검증 (await 추가 필요)
            if required_permission:
                await self.check_permission(api_key_obj, required_permission)

            return api_key_obj, partner

        except AuthenticationError as e:
            logger.warning(f"Authentication failed: {e}")
            raise HTTPException(status_code=401, detail=str(e))
        except NotAllowedIPError as e:
            logger.warning(f"IP check failed: {e}")
            raise HTTPException(status_code=403, detail=f"IP address not allowed: {e}")
        except PermissionDeniedError as e:
            logger.warning(f"Permission check failed: {e}")
            raise HTTPException(status_code=403, detail=f"Permission denied: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error during request authentication: {e}")
            raise HTTPException(status_code=500, detail="Internal server error during authentication")

    async def authenticate_partner(self, login_data: LoginRequest) -> TokenResponse:
        """파트너 코드와 API 키로 파트너를 인증하고 토큰을 발급합니다."""
        
        partner = await self.partner_repo.get_partner_by_code(login_data.partner_code)
        if not partner or partner.status != PartnerStatus.ACTIVE:
            raise InvalidCredentialsError("Invalid partner code or partner is not active.")
        
        # API 키 검증
        api_key_record = await self.get_valid_api_key(partner.id, login_data.api_key)
        if not api_key_record:
            raise InvalidCredentialsError("Invalid API key.")
            
        # 액세스 토큰 생성 (partner_code 추가)
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(partner.id), "partner_code": partner.code, "type": "partner"}, # partner_code 추가
            expires_delta=access_token_expires
        )
        refresh_token = create_access_token(
            data={"sub": str(partner.id), "type": "refresh"},
            expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            secret_key=settings.REFRESH_TOKEN_SECRET_KEY
        )

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    async def get_valid_api_key(self, partner_id: UUID, api_key: str) -> Optional[ApiKey]:
        """유효한 API 키 정보를 조회합니다."""
        # 실제 DB 조회 로직 필요
        key_hash = get_password_hash(api_key)
        
        # 예시: 해시된 키로 조회 (실제 구현 필요)
        # result = await self.db.execute(
        #     select(ApiKey).where(
        #         ApiKey.partner_id == partner_id,
        #         ApiKey.key == key_hash, # 해시된 값으로 비교
        #         ApiKey.is_active == True,
        #         (ApiKey.expires_at == None) | (ApiKey.expires_at > datetime.utcnow())
        #     )
        # )
        # return result.scalars().first()
        logger.warning(f"AuthService.get_valid_api_key is not fully implemented. Need DB query for partner {partner_id} with key hash.")
        # 임시 반환값 (테스트 목적)
        from backend.models.domain.partner import ApiKey as APIKeyModel # 이름 충돌 피하기
        class MockApiKey(APIKeyModel):
            key = key_hash # 임시로 해시된 키 설정
        return MockApiKey(id=uuid4(), partner_id=partner_id, key=key_hash, name='TestKey', is_active=True) # 임시 객체 반환