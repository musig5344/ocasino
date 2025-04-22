"""
인증 서비스
API 키 인증, 권한 관리 등 비즈니스 로직 담당
"""
import logging
from uuid import UUID
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
import ipaddress

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status, Request

from backend.models.domain.partner import Partner, ApiKey
from backend.repositories.partner_repository import PartnerRepository
from backend.services.partner.partner_service import PartnerService
from backend.core.security import hash_api_key
from backend.core.exceptions import AuthenticationError, NotAllowedIPError, PermissionDeniedError
from backend.cache.redis_cache import get_redis_client

logger = logging.getLogger(__name__)

class AuthService:
    """인증 서비스"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.partner_repo = PartnerRepository(db)
        self.partner_service = PartnerService(db)
        self.redis = get_redis_client()
    
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
        # 캐시 확인
        cache_key = f"api_key:{hash_api_key(api_key)}"
        cached_data = await self.redis.get(cache_key)
        
        if cached_data:
            # 이미 인증된 키 (캐시 사용)
            # 여기서는 API 키 객체만 필요한 정보를 캐싱하는 방식을 사용
            api_key_id = cached_data.decode('utf-8')
            api_key_obj = await self.partner_repo.get_active_api_key(hash_api_key(api_key))
            
            if not api_key_obj:
                # 캐시가 있지만 DB에서 키를 찾을 수 없는 경우
                # (키가 비활성화되었거나 삭제된 경우)
                await self.redis.delete(cache_key)
                raise AuthenticationError("Invalid API key")
            
            # 파트너 조회
            partner = await self.partner_repo.get_partner_by_id(api_key_obj.partner_id)
            
            # 마지막 사용 시간 업데이트 (빈번한 DB 업데이트 방지)
            current_time = datetime.utcnow()
            if api_key_obj.last_used_at is None or (current_time - api_key_obj.last_used_at) > timedelta(hours=1):
                api_key_obj.last_used_at = current_time
                await self.db.flush()
            
            return api_key_obj, partner
        
        # DB에서 인증
        api_key_obj = await self.partner_repo.get_active_api_key(hash_api_key(api_key))
        
        if not api_key_obj:
            raise AuthenticationError("Invalid API key")
        
        # 만료 확인
        if api_key_obj.expires_at and api_key_obj.expires_at <= datetime.utcnow():
            raise AuthenticationError("API key expired")
        
        # 파트너 조회
        partner = await self.partner_repo.get_partner_by_id(api_key_obj.partner_id)
        
        if not partner:
            raise AuthenticationError("Partner not found")
        
        # 파트너 활성 상태 확인
        if partner.status != "active":
            raise AuthenticationError(f"Partner is {partner.status}")
        
        # 사용 시간 업데이트
        api_key_obj.last_used_at = datetime.utcnow()
        await self.db.flush()
        
        # 캐시 저장 (10분)
        await self.redis.set(cache_key, str(api_key_obj.id), ex=600)
        
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
    
    async def authenticate_request(
        self, request: Request, required_permission: Optional[str] = None
    ) -> Tuple[ApiKey, Partner]:
        """
        요청 인증 및 권한 확인
        
        Args:
            request: HTTP 요청
            required_permission: 필요한 권한
            
        Returns:
            Tuple[ApiKey, Partner]: API 키 및 파트너 객체
            
        Raises:
            HTTPException: 인증 또는 권한 확인 실패 시
        """
        # API 키 추출
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key missing"
            )
        
        try:
            # API 키 인증
            api_key_obj, partner = await self.authenticate_api_key(api_key)
            
            # IP 화이트리스트 확인
            client_ip = request.client.host
            await self.verify_ip_whitelist(partner.id, client_ip)
            
            # 권한 확인 (필요한 경우)
            if required_permission:
                await self.check_permission(api_key_obj, required_permission)
            
            return api_key_obj, partner
        
        except AuthenticationError as e:
            logger.warning(f"Authentication failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e)
            )
        except NotAllowedIPError as e:
            logger.warning(f"IP not allowed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e)
            )
        except PermissionDeniedError as e:
            logger.warning(f"Permission denied: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(e)
            )