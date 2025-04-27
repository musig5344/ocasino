"""
게임 세션 서비스
"""
import logging
from uuid import UUID
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from backend.models.domain.game import GameSession
from backend.schemas.game import GameSessionCreate
from backend.repositories.game_repository import GameRepository # 임시로 GameRepository 사용
from backend.core.exceptions import DuplicateGameSessionError, DatabaseError
from backend.models.enums import SessionStatus # Assuming SessionStatus Enum exists
import secrets # For token generation

logger = logging.getLogger(__name__)

# Define session status constants if not using Enum
# ACTIVE_SESSION = "active"
# Define token length
SESSION_TOKEN_LENGTH = 32

class GameSessionService:
    """게임 세션 관련 로직 처리"""
    def __init__(self, db: AsyncSession):
        self.db = db
        # TODO: GameSessionRepository 를 구현하고 사용해야 함
        self.repo = GameRepository(db) 

    async def get_game_session(self, session_id: UUID) -> Optional[GameSession]:
        """세션 ID로 게임 세션 조회"""
        logger.warning(f"GameSessionService.get_game_session is not fully implemented. Called with id: {session_id}")
        # 실제 구현 필요
        # return await self.repo.get_session_by_id(session_id)
        return None

    async def list_game_sessions(
        self, 
        game_id: Optional[UUID] = None,
        partner_id: Optional[UUID] = None, 
        player_id: Optional[UUID] = None, # Added player_id filter
        status: Optional[str] = None, # Added status filter
        skip: int = 0, 
        limit: int = 100, 
        sort_by: Optional[str] = None, 
        sort_order: str = 'asc'
    ) -> Tuple[List[GameSession], int]:
        """게임 세션 목록 조회"""
        logger.warning("GameSessionService.list_game_sessions is not fully implemented.")
        # 실제 구현 필요
        # filters = {"game_id": game_id, "partner_id": partner_id} # 필터 구성
        # return await self.repo.list_sessions(skip, limit, filters, sort_by, sort_order)
        return [], 0

    def _generate_session_token(self) -> str:
        """고유한 세션 토큰 생성"""
        return secrets.token_hex(SESSION_TOKEN_LENGTH // 2)

    async def create_game_session(self, session_data: GameSessionCreate) -> GameSession:
        """새 게임 세션 생성 (동시성 제어 포함)
        
        동일한 플레이어와 게임에 대해 활성 상태의 세션이 이미 존재하는 경우
        생성을 방지하거나 기존 세션을 반환합니다.
        
        Args:
            session_data: 생성할 세션 데이터 (GameSessionCreate 스키마)

        Returns:
            GameSession: 생성되거나 기존의 활성 세션
            
        Raises:
            DatabaseError: 데이터베이스 오류 발생 시
            DuplicateGameSessionError: 동시 생성 시도 중 충돌 발생 시 (선택적)
        """
        # Use provided player_id and game_id from schema
        player_id = session_data.player_id
        game_id = session_data.game_id

        try:
            async with self.db.begin(): # Start transaction
                # 1. Check for existing active session with lock
                existing_session = await self.repo.get_active_session_for_player_game(
                    player_id=player_id, 
                    game_id=game_id,
                    lock=True # Attempt to lock the related Player row
                )
                
                if existing_session:
                    logger.warning(f"Active session already exists for player {player_id} and game {game_id}. Returning existing session {existing_session.id}.")
                    # Optionally update timestamp or other fields if needed
                    # existing_session.last_activity = datetime.utcnow()
                    return existing_session
                
                # 2. If no active session, create a new one
                session_token = self._generate_session_token()
                
                # Create GameSession ORM model instance
                new_session = GameSession(
                    player_id=player_id,
                    partner_id=session_data.partner_id,
                    game_id=game_id,
                    token=session_token,
                    status=SessionStatus.ACTIVE if 'SessionStatus' in locals() else 'active', # Use Enum or string
                    player_ip=session_data.metadata.get('ip_address') if session_data.metadata else None,
                    device_info=session_data.metadata.get('device_info') if session_data.metadata else None,
                    session_data=session_data.metadata.get('session_data') if session_data.metadata else None,
                    # start_time, created_at, updated_at have defaults
                )
                
                # 3. Save the new session via repository
                created_session = await self.repo.create_session(new_session)
            
            # Transaction committed automatically if no exceptions
            logger.info(f"Successfully created new game session {created_session.id} for player {player_id}, game {game_id}.")
            return created_session
            
        except IntegrityError as e:
            # This likely occurs if the unique constraint (uq_active_player_game_session) 
            # is violated due to a concurrent request that committed first.
            await self.db.rollback() # Rollback the current transaction
            logger.warning(
                f"IntegrityError (likely unique constraint violation) creating session for player {player_id}, game {game_id}. Checking again. Detail: {e}"
            )
            # After rollback, try fetching the session again (without lock, as it should exist now)
            existing_session = await self.repo.get_active_session_for_player_game(
                player_id=player_id, 
                game_id=game_id,
                lock=False
            )
            if existing_session:
                logger.info("Found existing active session after IntegrityError rollback.")
                return existing_session
            else:
                # This case is unexpected if the constraint was the cause.
                logger.error(
                    f"Could not find existing session after IntegrityError for player {player_id}, game {game_id}. Constraint: {e.constraint_name if hasattr(e, 'constraint_name') else 'N/A'}"
                )
                raise DuplicateGameSessionError(
                     f"Failed to create session due to potential conflict, but couldn't retrieve existing one. Constraint: {e.constraint_name if hasattr(e, 'constraint_name') else 'N/A'}"                    
                ) from e
        except Exception as e:
            # Handle other potential errors during session creation or locking
            await self.db.rollback() # Ensure rollback on any error
            logger.exception(
                f"Failed to create game session for player {player_id}, game {game_id}: {e}"
            )
            # Raise a general database error or a more specific one if identifiable
            raise DatabaseError(f"Could not create game session: {e}") from e 