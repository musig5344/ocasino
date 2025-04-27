from fastapi import APIRouter, Depends, Body, Query, Path, status, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any, Annotated
import logging
from uuid import UUID

# TODO: Update these imports based on new structure
# from backend.api.dependencies.db import get_db # 이전 경로 주석 처리
# from backend.api.dependencies.auth import (
#     get_current_partner_id, require_permission, get_ip_address, get_current_permissions
# ) # 이전 경로 주석 처리
# from backend.api.dependencies.common import common_pagination_params, common_sort_params # 이전 경로 주석 처리

from backend.core.dependencies import (
    get_db, 
    get_current_partner_id, 
    require_permission, 
    get_ip_address, 
    get_current_permissions,
    common_pagination_params,
    common_sort_params
) # 새로운 공통 의존성 사용

from backend.schemas.game import (
    Game, GameSession, GameCreate, GameUpdate, GameSessionCreate, GameList, GameSessionList,
    GameProviderList, GameProviderResponse, GameProvider
)
# Services are now imported via dependencies
# from backend.services.game.game_service import GameService 
# from backend.services.game.game_session_service import GameSessionService

# Import dependencies from the new location
from backend.games.dependencies import get_game_service, get_game_session_service

# --- Add missing GameService import ---
from backend.services.game.game_service import GameService
# --- Add missing GameSessionService import ---
from backend.services.game.game_session_service import GameSessionService

from backend.core.exceptions import (
    InvalidInputError, 
    ServiceUnavailableException, ConflictError, ValidationError, AuthorizationError,
    GameNotFoundError, GameSessionNotFoundError, PermissionDeniedError
)
from backend.core.schemas import ErrorResponse, StandardResponse, PaginatedResponse
# from backend.schemas.common import ErrorResponse # 이전 경로 주석 처리

# Import standard response utils and schemas
from backend.utils.response import success_response, paginated_response

router = APIRouter(tags=["Games & Providers"]) # Prefix handled in api.py
logger = logging.getLogger(__name__)

@router.get(
    "",
    response_model=PaginatedResponse[Game], 
    summary="게임 목록 조회",
    description="""
    플랫폼에서 제공하고 파트너가 접근 가능한 게임 목록을 조회합니다. 
    페이지네이션, 필터링(이름, 제공자, 유형, 상태), 정렬 기능을 지원합니다.
    
    - **일반 파트너 (`games.read` 권한):** `active` 상태의 게임만 조회할 수 있으며, `status` 쿼리 파라미터는 무시됩니다.
    - **관리자 (`games.admin` 권한):** 모든 상태의 게임을 조회하고 `status` 파라미터로 필터링할 수 있습니다.
    """,
    responses={
        status.HTTP_200_OK: {"description": "게임 목록 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "게임 목록 조회 권한 없음"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "잘못된 필터, 정렬 또는 페이지네이션 파라미터"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "게임 목록 조회 중 내부 서버 오류 발생"}
    }
)
async def list_games(
    name: Optional[str] = Query(None, description="게임 이름(name)으로 부분 문자열 검색 (대소문자 구분 없음)", example="Mega Wheel"),
    provider_id: Optional[UUID] = Query(None, description="특정 게임 제공자(provider)의 UUID로 필터링", example="d290f1ee-6c54-4b01-90e6-d701748f0851"),
    game_type: Optional[str] = Query(None, description="게임 유형(type) 필터링", example="live_casino"),
    status: Optional[str] = Query(None, description="게임 상태(status) 필터링 (관리자 전용: active, inactive, maintenance)", regex="^(active|inactive|maintenance)$", example="active"),
    pagination: Dict[str, Any] = Depends(common_pagination_params),
    sorting: Dict[str, Optional[str]] = Depends(common_sort_params),
    game_service: GameService = Depends(get_game_service), # Using updated dependency from games.dependencies
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    사용 가능한 게임 목록을 필터링하고 정렬하여 조회합니다.
    
    - **name**: 게임 이름 부분 문자열 필터.
    - **provider_id**: 게임 제공자 UUID 필터.
    - **game_type**: 게임 유형 필터.
    - **status**: 게임 상태 필터 (`active`, `inactive`, `maintenance`). 관리자만 적용 가능.
    - **pagination**: 페이지네이션 파라미터 (`offset`, `limit`).
    - **sorting**: 정렬 파라미터 (`sort_by`, `sort_order`).
    
    **권한 요구사항:** `games.read` (활성 게임 조회) 또는 `games.admin` (모든 게임 조회)
    """
    is_admin = "games.admin" in requesting_permissions
    can_read = "games.read" in requesting_permissions

    if not can_read and not is_admin:
        raise PermissionDeniedError("Permission denied to list games")
        
    query_status = status
    if not is_admin:
        query_status = "active" 
        if status and status != "active":
             logger.debug(f"Non-admin attempted to filter by status '{status}', forcing to 'active'.")
             
    games, total = await game_service.list_games(
        skip=pagination["offset"],
        limit=pagination["limit"],
        name=name,
        provider_id=provider_id,
        game_type=game_type,
        status=query_status,
        sort_by=sorting.get("sort_by"),
        sort_order=sorting.get("sort_order", "asc"),
    )
    
    return paginated_response(
        items=games,
        total=total,
        page=pagination.get("page", 1),
        page_size=pagination["limit"]
    )

@router.get(
    "/{game_id}", 
    response_model=StandardResponse[Game], 
    summary="특정 게임 상세 정보 조회",
    description="""
    지정된 ID의 게임 상세 정보를 조회합니다.
    
    - **일반 파트너 (`games.read` 권한):** `active` 상태의 게임 정보만 조회할 수 있습니다. 비활성 게임 조회 시 404 오류가 반환됩니다.
    - **관리자 (`games.admin` 권한):** 모든 상태의 게임 정보를 조회할 수 있습니다.
    """,
    responses={
        status.HTTP_200_OK: {"description": "게임 정보 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 게임 정보 조회 권한 없음"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정한 ID의 게임을 찾을 수 없거나 접근 권한 없음"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "게임 정보 조회 중 내부 서버 오류 발생"}
    }
)
async def get_game(
    game_id: UUID = Path(..., description="조회할 게임의 고유 ID"),
    game_service: GameService = Depends(get_game_service), # Use local dependency
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    특정 게임의 상세 정보를 조회합니다.
    
    - **game_id**: 조회 대상 게임의 UUID.
    
    **권한 요구사항:** `games.read` (활성 게임) 또는 `games.admin` (모든 게임)
    """
    is_admin = "games.admin" in requesting_permissions
    can_read = "games.read" in requesting_permissions

    if not can_read and not is_admin:
        raise PermissionDeniedError("Permission denied to view game details")
        
    game = await game_service.get_game(game_id)
    
    if not is_admin and game.status != "active":
         logger.info(f"Non-admin access denied for non-active game {game_id}")
         raise GameNotFoundError(f"Game '{game_id}' not found or access denied.")

    return success_response(data=game)

@router.post(
    "",
    response_model=StandardResponse[Game], 
    status_code=status.HTTP_201_CREATED, 
    summary="새 게임 생성 (관리자 전용)",
    description="""
    새로운 게임을 시스템에 등록합니다. 게임 코드(`external_id`)와 제공자(`provider_id`) 조합은 고유해야 합니다.
    이 작업은 `games.create` 권한을 가진 관리자만 수행할 수 있습니다.
    """,
    responses={
        status.HTTP_201_CREATED: {"description": "게임 생성 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "게임 생성 권한 없음"},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "동일한 제공자의 동일한 외부 ID(external_id)를 가진 게임이 이미 존재함"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "요청 데이터 유효성 검사 오류 (예: 필수 필드 누락, 잘못된 형식, 존재하지 않는 provider_id)"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "게임 생성 중 내부 서버 오류 발생"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse, "description": "지정된 게임 제공사가 현재 비활성 상태임"}
    }
)
async def create_game(
    game_data: GameCreate,
    game_service: GameService = Depends(get_game_service), # Use local dependency
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    새로운 게임을 시스템에 등록합니다.
    
    - **game_data**: 생성할 게임의 상세 정보 (GameCreate 스키마).
    
    **권한 요구사항:** `games.create`
    """
    if "games.create" not in requesting_permissions:
         raise PermissionDeniedError("Permission denied to create games")
    
    game = await game_service.create_game(game_data)
    logger.info(f"Game created: {game.id} ({game.name}) with external_id {game.external_id}")
    return success_response(data=game, message="Game created successfully.")

@router.put(
    "/{game_id}", 
    response_model=StandardResponse[Game], 
    summary="게임 정보 업데이트 (관리자 전용)",
    description="""
    지정된 ID의 게임 정보를 업데이트합니다. 요청 본문에 포함된 필드만 업데이트됩니다 (부분 업데이트).
    이 작업은 `games.update` 권한을 가진 관리자만 수행할 수 있습니다.
    """,
    responses={
        status.HTTP_200_OK: {"description": "게임 정보 업데이트 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "게임 정보 업데이트 권한 없음"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "업데이트할 게임을 찾을 수 없음"},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "수정하려는 정보가 다른 게임과 충돌 (예: external_id)"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "요청 데이터 유효성 검사 오류"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "게임 정보 업데이트 중 내부 서버 오류 발생"}
    }
)
async def update_game(
    game_id: Annotated[UUID, Path(..., description="업데이트할 게임의 고유 ID")],
    game_data: Annotated[GameUpdate, Body(...)],
    game_service: Annotated[GameService, Depends(get_game_service)],
    requesting_permissions: Annotated[List[str], Depends(get_current_permissions)]
):
    """
    지정된 게임의 정보를 업데이트합니다.
    
    - **game_id**: 업데이트 대상 게임의 UUID.
    - **game_data**: 업데이트할 게임 정보 (GameUpdate 스키마, 부분 업데이트).
    
    **권한 요구사항:** `games.update`
    """
    if "games.update" not in requesting_permissions:
         raise PermissionDeniedError("Permission denied to update games")
    
    updated_game = await game_service.update_game(game_id, game_data)
    logger.info(f"Game updated: {updated_game.id} ({updated_game.name})")
    return success_response(data=updated_game, message="Game updated successfully.")

@router.delete(
    "/{game_id}", 
    response_model=StandardResponse[None], 
    status_code=status.HTTP_200_OK, 
    summary="게임 삭제 (관리자 전용)",
    description="""
    지정된 ID의 게임을 시스템에서 논리적으로 삭제합니다 (예: 상태를 `deleted`로 변경). 
    물리적 삭제는 정책에 따라 달라질 수 있습니다.
    이 작업은 `games.delete` 권한을 가진 관리자만 수행할 수 있습니다.
    """,
    responses={
        status.HTTP_200_OK: {"description": "게임 삭제(비활성) 처리 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "게임 삭제 권한 없음"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "삭제할 게임을 찾을 수 없음"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "게임 삭제 처리 중 내부 서버 오류 발생"}
    }
)
async def delete_game(
    game_id: UUID = Path(..., description="삭제할 게임의 고유 ID"),
    game_service: GameService = Depends(get_game_service), # Use local dependency
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    지정된 게임을 논리적으로 삭제합니다.
    
    - **game_id**: 삭제 대상 게임의 UUID.
    
    **권한 요구사항:** `games.delete`
    """
    if "games.delete" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to delete games")
    
    await game_service.delete_game(game_id)
    logger.info(f"Game {game_id} marked for deletion")
    return success_response(message="Game successfully marked for deletion.")


# --- Game Session Endpoints --- 

@router.get(
    "/sessions",
    response_model=PaginatedResponse[GameSession], 
    tags=["Game Sessions"],
    summary="게임 세션 목록 조회",
    description="""
    게임 세션 목록을 조회합니다. 페이지네이션, 필터링(게임 ID, 플레이어 ID, 상태), 정렬 기능을 지원합니다.
    
    - **파트너 (`game_sessions.read.self` 권한):** 자신의 `partner_id` 와 연결된 세션만 조회할 수 있습니다.
    - **관리자 (`game_sessions.read.all` 권한):** 모든 파트너의 게임 세션을 조회할 수 있습니다.
    """,
    responses={
        status.HTTP_200_OK: {"description": "게임 세션 목록 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "게임 세션 목록 조회 권한 없음"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "잘못된 필터, 정렬 또는 페이지네이션 파라미터"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "게임 세션 목록 조회 중 내부 서버 오류 발생"}
    }
)
async def list_game_sessions(
    game_id: Optional[UUID] = Query(None, description="특정 게임 UUID로 세션 필터링"),
    player_id: Optional[str] = Query(None, description="특정 플레이어 ID(문자열)로 세션 필터링"),
    status: Optional[str] = Query(None, description="세션 상태(status) 필터링", regex="^(active|completed|terminated|error)$", example="active"),
    pagination: Dict[str, Any] = Depends(common_pagination_params),
    sorting: Dict[str, Optional[str]] = Depends(common_sort_params),
    session_service: GameSessionService = Depends(get_game_session_service), # Use local dependency
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    게임 세션 목록을 필터링하고 정렬하여 조회합니다.
    
    - **game_id**: 게임 UUID 필터.
    - **player_id**: 플레이어 ID 필터.
    - **status**: 세션 상태 필터.
    - **pagination**: 페이지네이션 파라미터.
    - **sorting**: 정렬 파라미터.
    
    **권한 요구사항:** `game_sessions.read.self` 또는 `game_sessions.read.all`
    """
    can_read_all = "game_sessions.read.all" in requesting_permissions
    can_read_self = "game_sessions.read.self" in requesting_permissions

    if not can_read_all and not can_read_self:
        raise PermissionDeniedError("Permission denied to list game sessions")
        
    target_partner_id = None if can_read_all else requesting_partner_id

    sessions, total = await session_service.list_sessions(
        skip=pagination["offset"],
        limit=pagination["limit"],
        partner_id=target_partner_id,
        game_id=game_id,
        player_id=player_id,
        status=status,
        sort_by=sorting.get("sort_by"),
        sort_order=sorting.get("sort_order", "asc"),
    )
    
    return paginated_response(
        items=sessions,
        total=total,
        page=pagination.get("page", 1),
        page_size=pagination["limit"]
    )

@router.get(
    "/sessions/{session_id}", 
    response_model=StandardResponse[GameSession], 
    tags=["Game Sessions"],
    summary="특정 게임 세션 상세 정보 조회",
    description="""
    지정된 ID의 게임 세션 상세 정보를 조회합니다. 
    
    - **파트너 (`game_sessions.read.self` 권한):** 자신의 `partner_id` 와 연결된 세션만 조회할 수 있습니다.
    - **관리자 (`game_sessions.read.all` 권한):** 모든 게임 세션을 ID로 조회할 수 있습니다.
    """,
    responses={
        status.HTTP_200_OK: {"description": "게임 세션 정보 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 게임 세션 조회 권한 없음"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정한 ID의 게임 세션을 찾을 수 없거나 접근 권한 없음"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "게임 세션 정보 조회 중 내부 서버 오류 발생"}
    }
)
async def get_game_session(
    session_id: UUID = Path(..., description="조회할 게임 세션의 고유 ID"),
    session_service: GameSessionService = Depends(get_game_session_service), # Use local dependency
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    특정 게임 세션의 상세 정보를 조회합니다.
    
    - **session_id**: 조회 대상 게임 세션의 UUID.
    
    **권한 요구사항:** `game_sessions.read.self` 또는 `game_sessions.read.all`
    """
    can_read_all = "game_sessions.read.all" in requesting_permissions
    can_read_self = "game_sessions.read.self" in requesting_permissions
    
    session = await session_service.get_session(session_id)

    if not can_read_all:
        if not can_read_self or session.partner_id != requesting_partner_id:
            logger.warning(f"Permission denied for partner {requesting_partner_id} to view session {session_id}")
            raise GameSessionNotFoundError(f"Session '{session_id}' not found or access denied.")

    return success_response(data=session)

@router.post(
    "/sessions", 
    response_model=StandardResponse[GameSession], 
    status_code=status.HTTP_201_CREATED, 
    tags=["Game Sessions"],
    summary="새 게임 세션 생성",
    description="""
    플레이어가 특정 게임을 시작하기 위한 새로운 게임 세션을 생성합니다.
    요청 시 게임의 활성 상태 및 제공자의 활성 상태를 확인합니다.
    파트너는 자신의 `partner_id`로만 세션을 생성할 수 있습니다.
    """,
    responses={
        status.HTTP_201_CREATED: {"description": "게임 세션 생성 성공"},
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse, "description": "잘못된 입력값 (예: 논리적 오류, 중복 세션)"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 게임에 대한 세션 생성 권한 없음"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "세션 생성을 위한 게임 정보를 찾을 수 없음"},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "플레이어의 동일 게임 활성 세션이 이미 존재함"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "요청 데이터 유효성 오류 (Pydantic)"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "게임 세션 생성 중 내부 서버 오류 발생"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse, "description": "게임 또는 게임 제공사가 현재 이용 불가 상태"}
    }
)
async def create_game_session(
    session_data: GameSessionCreate,
    session_service: GameSessionService = Depends(get_game_session_service), # Use local dependency
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    ip_address: str = Depends(get_ip_address),
    requesting_permissions: List[str] = Depends(get_current_permissions) # Example: Check 'game_sessions.create' permission
):
    """
    새로운 게임 세션을 생성합니다.
    
    - **session_data**: 세션 생성 정보 (GameSessionCreate 스키마).
    
    **권한 요구사항:** `game_sessions.create` (예시)
    """
    if "game_sessions.create" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to create game sessions")
        
    session = await session_service.create_session(
        session_data=session_data,
        requesting_partner_id=requesting_partner_id, 
        ip_address=ip_address
    )
    logger.info(f"Game session created: {session.id} for game {session_data.game_id}, player {session_data.player_id}")
    return success_response(data=session, message="Game session created successfully.")


# --- Game Provider Endpoints --- (Consider moving to a separate provider module)

@router.get(
    "/providers", 
    response_model=PaginatedResponse[GameProviderResponse],
    tags=["Game Providers"],
    summary="게임 제공사 목록 조회",
    description="""
    플랫폼에 연동된 게임 제공사 목록을 조회합니다.
    - 일반 파트너는 `active` 상태의 제공사 정보만 조회할 수 있습니다.
    - 관리자(`games.admin` 권한)는 모든 상태의 제공사 정보 및 API URL을 조회할 수 있습니다.
    """,
    responses={
        status.HTTP_200_OK: {"description": "게임 제공사 목록 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "게임 제공사 목록 조회 권한 없음"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"description": "잘못된 필터 또는 정렬 파라미터"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "게임 제공사 목록 조회 중 내부 서버 오류 발생"}
    }
)
async def list_game_providers(
    name: Optional[str] = Query(None, description="제공사 이름으로 부분 문자열 검색"),
    status: Optional[str] = Query(None, description="제공사 상태 필터링 (예: active, inactive)", example="active"),
    integration_type: Optional[str] = Query(None, description="통합 유형 필터링 (예: direct, aggregator)", example="direct"),
    pagination: dict = Depends(common_pagination_params),
    sorting: dict = Depends(common_sort_params),
    game_service: GameService = Depends(get_game_service), # Use GameService for providers for now
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    게임 제공사 목록을 조회합니다.
    
    **권한 요구사항:** `games.read` 또는 `games.admin`
    """
    is_admin = "games.admin" in requesting_permissions
    can_read = "games.read" in requesting_permissions

    if not can_read and not is_admin:
        raise PermissionDeniedError("Permission denied to list game providers")
        
    query_status = status
    if not is_admin:
        query_status = "active" 
        if status and status != "active":
             logger.debug(f"Non-admin attempted to filter provider status by '{status}', forcing to 'active'.")

    filters = {
        "name__icontains": name,
        "status": query_status,
        "integration_type": integration_type
    }
    active_filters = {k: v for k, v in filters.items() if v is not None}
    
    providers, total = await game_service.list_providers(
         skip=pagination["offset"],
         limit=pagination["limit"],
         filters=active_filters,
         sort_by=sorting.get("sort_by"),
         sort_order=sorting.get("sort_order", "asc"),
         include_sensitive=is_admin
    )
    
    response_items = []
    for provider in providers:
         if is_admin:
             response_items.append(GameProviderResponse(**provider.model_dump()))
         else:
              response_items.append(GameProvider(**provider.model_dump())) 
              
    return paginated_response(
         items=response_items,
         total=total,
         page=pagination.get("page", 1),
         page_size=pagination["limit"]
    )

# TODO: Add endpoints for managing game providers (CRUD - admin only)
# POST /providers
# GET /providers/{provider_id}
# PUT /providers/{provider_id}
# DELETE /providers/{provider_id} 