"""
Core/Common dependencies for the API
"""
from typing import AsyncGenerator, Dict, Any, List, Optional
from uuid import UUID
import logging

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

# Adjust these imports based on your actual project structure
from backend.db.database import get_db as get_db_session # Renamed to avoid conflict
from backend.cache.redis_cache import get_redis_client
from backend.services.auth.auth_service import AuthService
from backend.core.exceptions import AuthenticationError
from backend.utils.request_context import get_request_attribute

logger = logging.getLogger(__name__)

# --- Database Dependency --- 

async def get_db() -> AsyncGenerator[AsyncSession, None]: 
    """
    Provides a database session dependency.
    Uses the main session generator from database.py.
    """
    async for session in get_db_session():
        yield session

# --- Authentication Dependencies --- 

API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

def get_auth_service(
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(get_redis_client)
) -> AuthService:
    """AuthService dependency injector"""
    return AuthService(db=db, redis_client=redis_client)

async def get_current_partner_id(
    api_key: str = Depends(API_KEY_HEADER),
    auth_service: AuthService = Depends(get_auth_service)
) -> UUID:
    """
    Retrieves the partner ID from the current request context or authenticates via API key.
    """
    partner_id_ctx = get_request_attribute("partner_id")
    if partner_id_ctx:
        if isinstance(partner_id_ctx, UUID):
            return partner_id_ctx
        try:
            return UUID(partner_id_ctx)
        except (ValueError, TypeError):
            logger.warning(f"Invalid partner_id in request context: {partner_id_ctx}")
            pass

    try:
        api_key_obj, partner = await auth_service.authenticate_api_key(api_key)
        # Ensure partner is not None and has an id
        if partner and hasattr(partner, 'id'):
             return partner.id
        else:
             logger.error(f"Authentication succeeded but partner or partner.id is missing for API key: {api_key[:10]}...",) # Log partial key for security
             raise AuthenticationError("Partner information missing after authentication.")
    except AuthenticationError as e:
        logger.warning(f"API key authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
    except Exception as e:
        logger.exception(f"Unexpected error during partner ID retrieval: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

async def get_current_permissions(
    api_key: str = Depends(API_KEY_HEADER),
    auth_service: AuthService = Depends(get_auth_service)
) -> Dict[str, List[str]]:
    """
    Retrieves the permissions from the current request context or authenticates via API key.
    """
    permissions_ctx = get_request_attribute("permissions")
    if permissions_ctx and isinstance(permissions_ctx, dict):
        return permissions_ctx

    try:
        api_key_obj, partner = await auth_service.authenticate_api_key(api_key)
        # Check if api_key_obj has permissions attribute and it's a dictionary
        if hasattr(api_key_obj, 'permissions') and isinstance(api_key_obj.permissions, dict):
             return api_key_obj.permissions
        # Check if partner object has permissions (less likely but possible)
        elif hasattr(partner, 'permissions') and isinstance(partner.permissions, dict):
            logger.warning(f"Using permissions from partner object {partner.id}, not API key {api_key_obj.id}")
            return partner.permissions
        else:
             logger.error(f"Valid permissions attribute not found on API key {api_key_obj.id} or partner {getattr(partner, 'id', 'N/A')}.")
             return {} # Return empty dict if no permissions found
    except AuthenticationError as e:
        logger.warning(f"API key authentication failed while getting permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "APIKey"},
        )
    except Exception as e:
        logger.exception(f"Unexpected error during permissions retrieval: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

# Permission verification factory remains here as it depends on get_current_permissions
def require_permission(required_permission: str):
    """Factory for creating a dependency that verifies a required permission."""
    async def _verify_permissions_dependency(
        permissions: Dict[str, List[str]] = Depends(get_current_permissions)
    ):
        resource, action = required_permission.split(".")
        allowed = (
            (resource in permissions and action in permissions[resource]) or
            (resource in permissions and "*" in permissions[resource]) or
            ("*" in permissions and action in permissions["*"]) or
            ("*" in permissions and "*" in permissions["*"])
        )
        
        if not allowed:
            logger.warning(f"Permission denied: {required_permission} for request.") # Consider adding more request context if available
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {required_permission}",
            )
            
    return _verify_permissions_dependency

async def get_ip_address(request: Request) -> str:
    """Gets the client IP address from the request, considering proxies."""
    client_ip = get_request_attribute("client_ip")
    if client_ip:
        return str(client_ip) # Ensure it's a string
    
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    # Fallback to client.host if available
    if request.client and request.client.host:
        return request.client.host
    
    logger.warning("Could not determine client IP address.")
    return "unknown" # Return a default value or raise an error

# --- Common Parameter Dependencies --- 

def common_pagination_params(
    page: int = Query(1, ge=1, description="Page number starting from 1"), 
    limit: int = Query(20, ge=1, le=1000, description="Number of items per page") # Adjusted default limit
) -> Dict[str, int]:
    """Common pagination parameters (offset and limit, plus original page)."""
    offset = (page - 1) * limit
    return {"offset": offset, "limit": limit, "page": page}

def common_sort_params(
    sort_by: Optional[str] = Query(None, description="Field to sort by"),
    sort_order: str = Query("asc", description="Sort order (asc or desc)", pattern="^(asc|desc)$") # Added regex pattern
) -> Dict[str, Optional[str]]:
    """Common sorting parameters."""
    # Validation is now handled by the regex pattern in Query
    # if sort_order not in ["asc", "desc"]:
    #     sort_order = "asc"
    return {"sort_by": sort_by, "sort_order": sort_order.lower()} 