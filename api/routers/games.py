from fastapi import APIRouter, Depends, Body, Query, Path, status, Request
from sqlalchemy.orm import Session
from typing import Optional, List
import logging

from backend.api.dependencies.db import get_db
from backend.api.dependencies.auth import get_current_partner_id, verify_permissions, get_ip_address
from backend.api.dependencies.common import common_pagination_params, common_sort_params
from backend.models.schemas.game import (
    GameResponse, GameList, 
    GameSessionCreate, GameSessionResponse, GameSessionList,
    GameUpdateRequest, GameProviderResponse, GameProviderList
)
from backend.services.game.game_service import GameService
from backend.services.game.game_session_service import GameSessionService
from backend.api.errors.exceptions import ResourceNotFoundException, ForbiddenException, InvalidRequestException, ServiceUnavailableException

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("", response_model=GameList)
async def list_games(
    name: Optional[str] = Query(None, description="이름으로 필터링"),
    provider_id: Optional[str] = Query(None, description="게임 제공자 ID로 필터링"),
    game_type: Optional[str] = Query(None, description="게임 유형으로 필터링 (slot, table, live, other)"),
    status: Optional[str] = Query(None, description="상태로 필터링 (active, inactive, maintenance)"),
    pagination: dict = Depends(common_pagination_params),
    sorting: dict = Depends(common_sort_params),
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id)
):
    """
    사용 가능한 게임 목록 조회
    
    파트너는 활성 상태의 게임만 볼 수 있습니다.
    """
    game_service = GameService(db)
    
    # 일반 파트너는 활성 게임만 볼 수 있음
    is_admin = False
    try:
        await verify_permissions("games.admin")
        is_admin = True
    except:
        # 활성 게임만 필터링
        status = "active"
    
    # 게임 목록 조회
    games, total = await game_service.list_games(
        skip=pagination["skip"],
        limit=pagination["limit"],
        name=name,
        provider_id=provider_id,
        game_type=game_type,
        status=status,
        sort_by=sorting["sort_by"],
        sort_order=sorting["sort_order"],
        partner_id=partner_id
    )
    
    # 응답 생성
    items = []
    for game in games:
        items.append(GameResponse(
            id=game.id,
            provider_id=game.provider_id,
            external_id=game.external_id,
            name=game.name,
            type=game.type,
            rtp=game.rtp,
            volatility=game.volatility,
            status=game.status,
            created_at=game.created_at,
            updated_at=game.updated_at,
            provider=GameProviderResponse(
                id=game.provider.id,
                name=game.provider.name,
                integration_type=game.provider.integration_type,
                status=game.provider.status
            ) if game.provider else None
        ))
    
    return GameList(
        items=items,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"]
    )

@router.get("/{game_id}", response_model=GameResponse)
async def get_game(
    game_id: str = Path(..., description="게임 ID"),
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id)
):
    """
    게임 세부 정보 조회
    
    파트너는 활성 상태의 게임만 볼 수 있습니다.
    """
    game_service = GameService(db)
    
    # 게임 조회
    game = await game_service.get_game(game_id)
    if not game:
        raise ResourceNotFoundException("Game", game_id)
    
    # 일반 파트너는 활성 게임만 볼 수 있음
    if game.status != "active":
        try:
            await verify_permissions("games.admin")
        except:
            raise ResourceNotFoundException("Game", game_id)
    
    return GameResponse(
        id=game.id,
        provider_id=game.provider_id,
        external_id=game.external_id,
        name=game.name,
        type=game.type,
        rtp=game.rtp,
        volatility=game.volatility,
        status=game.status,
        created_at=game.created_at,
        updated_at=game.updated_at,
        provider=GameProviderResponse(
            id=game.provider.id,
            name=game.provider.name,
            integration_type=game.provider.integration_type,
            status=game.provider.status
        ) if game.provider else None
    )

@router.post("/session", response_model=GameSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_game_session(
    session_data: GameSessionCreate,
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id),
    ip_address: str = Depends(get_ip_address)
):
    """
    새 게임 세션 생성
    
    게임 세션을 생성하여 플레이어가 게임을 시작할 수 있도록 합니다.
    """
    # 게임 세션 생성 권한 확인
    await verify_permissions("games.session.create")
    
    game_service = GameService(db)
    session_service = GameSessionService(db)
    
    # 게임 존재 및 활성 상태 확인
    game = await game_service.get_game(session_data.game_id)
    if not game:
        raise ResourceNotFoundException("Game", session_data.game_id)
    
    if game.status != "active":
        raise InvalidRequestException(f"Game {game.id} is not active")
    
    # 게임 제공자 활성 상태 확인
    if game.provider.status != "active":
        raise ServiceUnavailableException(f"Game provider {game.provider.name} is currently unavailable")
    
    # 파트너 정보 설정
    session_data.partner_id = partner_id
    
    # IP 주소 및 추가 메타데이터 설정
    if not session_data.metadata:
        session_data.metadata = {}
    
    session_data.metadata["ip_address"] = ip_address
    
    try:
        # 게임 세션 생성
        session = await session_service.create_game_session(session_data)
        
        logger.info(f"Game session created: {session.id} for player {session_data.player_id}")
        
        return GameSessionResponse(
            id=session.id,
            game_id=session.game_id,
            player_id=session.player_id,
            partner_id=session.partner_id,
            status=session.status,
            external_session_id=session.external_session_id,
            game_url=session.session_data.get("game_url") if session.session_data else None,
            created_at=session.created_at,
            updated_at=session.updated_at,
            game=GameResponse(
                id=game.id,
                name=game.name,
                type=game.type,
                provider_id=game.provider_id,
                external_id=game.external_id
            )
        )
    except Exception as e:
        logger.error(f"Failed to create game session: {str(e)}")
        raise ServiceUnavailableException(f"Failed to create game session: {str(e)}")

@router.get("/session/{session_id}", response_model=GameSessionResponse)
async def get_game_session(
    session_id: str = Path(..., description="세션 ID"),
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id)
):
    """
    게임 세션 세부 정보 조회
    
    파트너는 자신의 세션만 볼 수 있습니다.
    """
    session_service = GameSessionService(db)
    
    # 세션 조회
    session = await session_service.get_game_session(session_id)
    if not session:
        raise ResourceNotFoundException("Game Session", session_id)
    
    # 권한 확인
    if session.partner_id != partner_id:
        try:
            await verify_permissions("games.admin")
        except:
            raise ForbiddenException("You can only view your own game sessions")
    
    # 게임 정보 조회
    game_service = GameService(db)
    game = await game_service.get_game(session.game_id)
    
    return GameSessionResponse(
        id=session.id,
        game_id=session.game_id,
        player_id=session.player_id,
        partner_id=session.partner_id,
        status=session.status,
        external_session_id=session.external_session_id,
        game_url=session.session_data.get("game_url") if session.session_data else None,
        created_at=session.created_at,
        updated_at=session.updated_at,
        game=GameResponse(
            id=game.id,
            name=game.name,
            type=game.type,
            provider_id=game.provider_id,
            external_id=game.external_id
        ) if game else None
    )

@router.get("/providers", response_model=GameProviderList)
async def list_game_providers(
    name: Optional[str] = Query(None, description="이름으로 필터링"),
    status: Optional[str] = Query(None, description="상태로 필터링 (active, inactive)"),
    integration_type: Optional[str] = Query(None, description="통합 유형으로 필터링 (direct, aggregator)"),
    pagination: dict = Depends(common_pagination_params),
    sorting: dict = Depends(common_sort_params),
    db: Session = Depends(get_db),
    partner_id: str = Depends(get_current_partner_id)
):
    """
    게임 제공자 목록 조회
    
    파트너는 활성 상태의 게임 제공자만 볼 수 있습니다.
    """
    game_service = GameService(db)
    
    # 일반 파트너는 활성 제공자만 볼 수 있음
    is_admin = False
    try:
        await verify_permissions("games.admin")
        is_admin = True
    except:
        # 활성 제공자만 필터링
        status = "active"
    
    # 게임 제공자 목록 조회
    providers, total = await game_service.list_game_providers(
        skip=pagination["skip"],
        limit=pagination["limit"],
        name=name,
        status=status,
        integration_type=integration_type,
        sort_by=sorting["sort_by"],
        sort_order=sorting["sort_order"]
    )
    
    # 응답 생성
    items = []
    for provider in providers:
        items.append(GameProviderResponse(
            id=provider.id,
            name=provider.name,
            api_url=provider.api_url if is_admin else None,  # API URL은 관리자에게만 표시
            integration_type=provider.integration_type,
            status=provider.status,
            created_at=provider.created_at
        ))
    
    return GameProviderList(
        items=items,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"]
    )