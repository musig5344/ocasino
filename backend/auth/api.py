from fastapi import APIRouter, Depends, Body, Query, Path, status, Request, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
import logging
import secrets
from uuid import UUID
from pydantic import BaseModel, Field

# Core dependencies
from backend.core.dependencies import (
    get_db, 
    get_current_partner_id, 
    require_permission,
    get_current_permissions
)

# Auth module dependencies
from backend.auth.dependencies import get_auth_service, get_api_key_service
# --- Add missing AuthService import ---
from backend.services.auth.auth_service import AuthService
# --- Add missing APIKeyService import ---
from backend.services.auth.api_key_service import APIKeyService

from backend.partners.schemas import (
    Partner as PartnerSchema, 
    ApiKey as ApiKeySchema, 
    ApiKeyCreate as ApiKeyCreateSchema,
    ApiKeyWithSecret as ApiKeyWithSecretSchema
)
from backend.core.exceptions import PartnerNotFoundError, APIKeyNotFoundError, AuthorizationError, InvalidCredentialsError
# Use common ErrorResponse (Updated Import)
from backend.core.schemas import ErrorResponse, StandardResponse
# from backend.schemas.common import ErrorResponse # 이전 경로 주석 처리

# Remove service imports if they are only used via dependencies
# from backend.services.auth.api_key_service import APIKeyService
# from backend.services.auth.auth_service import AuthService 

# --- Correct auth schema import ---
from backend.schemas.auth import LoginRequest, TokenResponse # Remove TokenData
# from backend.schemas.auth import LoginRequest, TokenData, TokenResponse # Old import

router = APIRouter() # Prefix will be handled in api.py
logger = logging.getLogger(__name__)

@router.post(
    "/login", 
    response_model=TokenResponse, 
    summary="파트너 로그인 및 토큰 발급", 
    tags=["Authentication"],
    description="파트너 코드와 API 키를 사용하여 로그인하고, API 접근에 사용할 액세스 토큰과 리프레시 토큰을 발급받습니다.",
    responses={
        status.HTTP_200_OK: {"description": "로그인 성공 및 토큰 발급"},
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "잘못된 자격 증명 (파트너 코드 또는 API 키 오류)"
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "요청 유효성 검사 오류"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
            "description": "로그인 처리 중 내부 서버 오류 발생"
        }
    }
)
async def login_for_access_token(
    login_data: LoginRequest = Body(..., example={"partner_code": "PARTNER001", "api_key": "your_initial_api_key"}),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    파트너 로그인을 처리하고 JWT 토큰을 발급합니다.
    
    - **login_data**: 파트너 코드와 API 키를 포함하는 요청 본문입니다.
    - **반환**: 성공 시 액세스 토큰과 리프레시 토큰을 포함한 응답을 반환합니다.
    
    **주요 에러:**
    - 401 Unauthorized: 제공된 자격 증명이 유효하지 않습니다.
    - 422 Unprocessable Entity: 요청 본문의 형식이 잘못되었습니다.
    - 500 Internal Server Error: 서버 내부 오류가 발생했습니다.
    """
    try:
        token_response = await auth_service.authenticate_partner(login_data)
        return token_response
    except InvalidCredentialsError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.exception(f"Login failed for user: {login_data.partner_code}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Login process failed internally")

@router.post(
    "/keys", 
    response_model=ApiKeyWithSecretSchema, 
    status_code=status.HTTP_201_CREATED,
    summary="신규 API 키 생성", 
    tags=["API Keys"],
    description="""
    새로운 API 키를 생성합니다. API 키는 플랫폼 API에 접근하기 위한 인증 수단입니다.
    
    - **요청 파트너:** 현재 인증된 파트너 ID (`requesting_partner_id`) 를 기반으로 생성 권한을 확인합니다.
    - **권한:** 일반적으로 파트너는 자신의 API 키만 생성할 수 있습니다 (`api_keys.create.self` 필요). 특정 관리자 권한 (`api_keys.create.all`) 이 있다면 다른 파트너의 키도 생성 가능합니다.
    - **비밀키:** 생성된 API 키의 비밀 값(`key_secret`)은 **이 응답에서만 반환**되므로 안전하게 저장해야 합니다.
    """,
    responses={
        status.HTTP_201_CREATED: {"description": "API 키가 성공적으로 생성되었습니다. 응답 본문에 비밀키가 포함됩니다."},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "요청 파트너가 해당 파트너의 API 키를 생성할 권한이 없습니다."},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "요청된 `partner_id`에 해당하는 파트너를 찾을 수 없습니다."},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "API 키 이름 중복 등 생성 충돌이 발생했습니다."},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "요청 데이터 유효성 검사 오류"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "API 키 생성 중 내부 서버 오류 발생"}
    }
)
async def create_api_key(
    api_key_data: ApiKeyCreateSchema,
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    api_key_service: APIKeyService = Depends(get_api_key_service),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    새로운 API 키를 생성하고 비밀키와 함께 반환합니다.

    - **api_key_data**: 생성할 API 키의 정보 (파트너 ID, 이름, 설명, 권한 등).
    - **requesting_partner_id**: API 키 생성을 요청하는 파트너의 ID (JWT 토큰에서 추출).
    
    **권한 요구사항:** `api_keys.create.self` 또는 `api_keys.create.all`
    
    **주요 에러:**
    - 403 Forbidden: 권한 부족.
    - 404 Not Found: 대상 파트너 없음.
    - 409 Conflict: 키 이름 중복 등.
    - 422 Unprocessable Entity: 요청 데이터 유효성 오류.
    - 500 Internal Server Error: 서버 내부 오류.
    """
    try:
        new_api_key_obj, key_secret = await api_key_service.create_api_key(
            partner_id=api_key_data.partner_id,
            name=api_key_data.name,
            requesting_partner_id=requesting_partner_id,
            description=api_key_data.description,
            permissions=api_key_data.permissions,
            created_by=str(requesting_partner_id)
        )
        return ApiKeyWithSecretSchema(
            id=new_api_key_obj.id,
            partner_id=new_api_key_obj.partner_id,
            name=new_api_key_obj.name,
            key=new_api_key_obj.key,
            description=new_api_key_obj.description,
            permissions=new_api_key_obj.permissions,
            created_at=new_api_key_obj.created_at,
            expires_at=new_api_key_obj.expires_at,
            last_used_at=new_api_key_obj.last_used_at,
            last_used_ip=new_api_key_obj.last_used_ip,
            is_active=new_api_key_obj.is_active,
            key_secret=key_secret
        )
    except PartnerNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Error creating API key")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create API key")

@router.get(
    "/keys", 
    response_model=List[ApiKeySchema], 
    summary="파트너의 API 키 목록 조회",
    tags=["API Keys"],
    description="활성 API 키 목록만 반환합니다 (비밀 키 제외). 파트너는 자신의 키만 조회할 수 있습니다.",
    responses={
        status.HTTP_200_OK: {"description": "API 키 목록 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "API 키 목록 조회 권한 없음"}
    }
)
async def list_api_keys(
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    api_key_service: APIKeyService = Depends(get_api_key_service),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    요청 파트너의 API 키 목록을 조회합니다.
    
    - **requesting_partner_id**: JWT 토큰 또는 API 키에서 식별된 파트너 ID.
    
    **권한 요구사항:** `api_keys.read.self`
    
    **주요 에러:**
    - 401 Unauthorized: 인증 필요.
    - 403 Forbidden: 권한 부족.
    - 500 Internal Server Error: 서버 내부 오류.
    """
    try:
        keys = await api_key_service.get_keys_by_partner(
            partner_id=requesting_partner_id, 
            requesting_partner_id=requesting_partner_id
        )
        return keys
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.exception(f"Error listing API keys for partner {requesting_partner_id}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list API keys")

@router.delete(
    "/keys/{api_key_id}", 
    status_code=status.HTTP_204_NO_CONTENT,
    summary="API 키 비활성화 (삭제 아님)", 
    tags=["API Keys"],
    description="""
    지정된 ID의 API 키를 비활성화합니다. 비활성화된 키는 더 이상 API 인증에 사용할 수 없습니다.
    키 레코드는 삭제되지 않고 비활성 상태로 유지됩니다.
    
    - 파트너는 자신의 API 키만 비활성화할 수 있습니다 (`api_keys.delete.self` 필요).
    - 관리자(`api_keys.delete.all` 권한)는 다른 파트너의 키도 비활성화할 수 있습니다.
    """,
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "API 키가 성공적으로 비활성화되었습니다."},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 API 키를 비활성화할 권한이 없습니다."},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정된 ID의 API 키를 찾을 수 없습니다."},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "API 키 비활성화 중 내부 서버 오류 발생"}
    }
)
async def deactivate_api_key(
    api_key_id: UUID = Path(..., description="비활성화할 API 키의 고유 ID"),
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    api_key_service: APIKeyService = Depends(get_api_key_service)
):
    """
    지정된 API 키를 비활성화합니다.
    
    - **api_key_id**: 비활성화할 대상 API 키의 UUID.
    - **requesting_partner_id**: 요청하는 파트너의 ID.
    
    **권한 요구사항:** `api_keys.delete.self` 또는 `api_keys.delete.all`
    
    **주요 에러:**
    - 401 Unauthorized: 인증 필요.
    - 403 Forbidden: 권한 부족.
    - 404 Not Found: 해당 API 키 없음.
    - 500 Internal Server Error: 서버 내부 오류.
    """
    try:
        await api_key_service.deactivate_api_key(api_key_id, requesting_partner_id)
    except APIKeyNotFoundError as e:
         raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.exception(f"Error deactivating API key {api_key_id}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to deactivate API key")
    
    return None

# --- IP Whitelist Endpoints (기능 구현 전까지 주석 처리) --- 

# @router.post("/ip-whitelist", response_model=IpWhitelistResponse, status_code=201)
# async def add_ip_to_whitelist(...):
    # ...

# @router.get("/ip-whitelist", response_model=IpWhitelistList)
# async def list_whitelisted_ips(...):
    # ...

# @router.delete("/ip-whitelist/{ip_address}")
# async def remove_ip_from_whitelist(...):
    # ...


# --- Token Refresh and Verification --- 

class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="액세스 토큰 재발급에 사용할 리프레시 토큰")

@router.post(
    "/refresh", 
    response_model=TokenResponse, 
    summary="액세스 토큰 갱신", 
    tags=["Authentication"],
    description="유효한 리프레시 토큰을 사용하여 만료된 액세스 토큰을 새로 발급받습니다.",
    responses={
        status.HTTP_200_OK: {"description": "토큰 갱신 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "리프레시 토큰이 유효하지 않거나 만료되었습니다."},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "요청 본문에 refresh_token 이 누락되었습니다."},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "토큰 갱신 중 내부 서버 오류 발생"}
    }
)
async def refresh_access_token(
    refresh_data: RefreshRequest = Body(...),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    리프레시 토큰을 사용하여 새로운 액세스 토큰과 리프레시 토큰을 발급합니다.
    
    - **refresh_data**: 리프레시 토큰을 포함하는 요청 본문.
    
    **주요 에러:**
    - 401 Unauthorized: 리프레시 토큰이 유효하지 않습니다.
    - 422 Unprocessable Entity: 요청 본문이 잘못되었습니다.
    - 500 Internal Server Error: 서버 내부 오류.
    """
    try:
        token_response = await auth_service.refresh_token(refresh_data.refresh_token)
        return token_response
    except InvalidCredentialsError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.exception("Error refreshing token")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Token refresh failed internally")

class VerifyResponse(BaseModel):
    valid: bool = Field(..., description="API 키 유효 여부")
    partner_id: UUID = Field(..., description="API 키에 연결된 파트너 ID")

@router.get(
    "/verify", 
    response_model=VerifyResponse, 
    summary="현재 API 키 유효성 검증", 
    tags=["Authentication"],
    description="""
    요청 헤더 (`X-API-Key`)에 포함된 API 키가 유효한지, 활성 상태인지, 그리고 만료되지 않았는지 확인합니다.
    파트너 시스템 통합 시 연결 테스트 용도로 사용할 수 있습니다.
    """,
    responses={
        status.HTTP_200_OK: {"description": "API 키가 유효합니다."},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "API 키가 제공되지 않았거나, 유효하지 않거나, 비활성 상태이거나, 만료되었습니다."}
    }
)
async def verify_api_key(
    partner_id: UUID = Depends(get_current_partner_id),
):
    """
    현재 요청에 사용된 API 키의 유효성을 검증하고 파트너 ID를 반환합니다.
    `get_current_partner_id` 의존성이 성공적으로 실행되면 키가 유효한 것으로 간주됩니다.
    
    - **partner_id**: 유효한 API 키로부터 식별된 파트너 ID.
    
    **성공**: API 키가 유효하고 파트너 ID를 성공적으로 가져오면 200 OK와 함께 유효성 및 파트너 ID 반환.
    **실패**: `get_current_partner_id`가 API 키를 검증하지 못하면 `AuthMiddleware` 또는 해당 의존성에서 401 Unauthorized 오류 발생.
    """
    # If this endpoint is reached, the API key is valid because get_current_partner_id dependency succeeded.
    return VerifyResponse(valid=True, partner_id=partner_id) 