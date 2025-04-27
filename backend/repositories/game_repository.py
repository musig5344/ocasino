"""
게임 데이터 접근 로직 (Repository)
"""
import logging
from typing import Optional, List, Dict, Any, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

# --- Updated Import --- 
from backend.core.repository import BaseRepository # Import BaseRepository
# 모델 임포트 (경로 확인 필요)
from backend.models.domain.game import Game, GameSession # Game 모델 정의 경로 확인 필요
from backend.models.domain.player import Player # Assuming a Player model exists for locking

logger = logging.getLogger(__name__)

class GameRepository(BaseRepository[Game]):
    """게임 관련 데이터베이스 작업을 처리합니다."""
    
    def __init__(self, session: AsyncSession):
        super().__init__(session, Game)
        # self.db is now the session via BaseRepository
        
    # get_game_by_id is replaced by BaseRepository.find_one
    # Example usage: await self.find_one(filters={"id": game_id}, load_relations=["provider"])

    # list_games is replaced by BaseRepository.find_many and BaseRepository.count
    # Service layer (_find_many) should call:
    # items = await self.find_many(skip=skip, limit=limit, filters=filters, sort_by=sort_by, sort_order=sort_order, load_relations=["provider"])
    # total = await self.count(filters=filters)

    # create_game is replaced by BaseRepository.create
    # Example usage in Service._create_entity:
    #   new_game = self.model_class(**data)
    #   created_game = await self.repository.create(new_game.__dict__) 
    #   return created_game
    # Need to ensure BaseRepository.create handles dict data correctly.

    # update_game is replaced by BaseRepository.update
    # Example usage in Service._update_entity:
    #   updated_game = await self.repository.update(entity.id, data)
    #   return updated_game

    # delete_game (hard delete) is replaced by BaseRepository.delete(id, soft_delete=False)
    # GameService._delete_entity uses this.

    # --- GameSession Repository Methods (Keep as they operate on GameSessionModel) --- 

    async def get_active_session_for_player_game(
        self, player_id: UUID, game_id: UUID, lock: bool = False
    ) -> Optional[GameSession]:
        """주어진 플레이어와 게임에 대한 활성(active) 세션을 조회합니다.
        
        Args:
            player_id: 플레이어 ID
            game_id: 게임 ID
            lock: True인 경우, 관련 플레이어 레코드에 대해 FOR NO KEY UPDATE 잠금을 시도합니다.
                  (주의: Player 모델 및 테이블이 필요합니다)

        Returns:
            Optional[GameSession]: 활성 세션 객체 또는 None
        """
        stmt = select(GameSession).where(
            GameSession.player_id == player_id,
            GameSession.game_id == game_id,
            GameSession.status == 'active'
        )

        if lock:
            # Player 테이블의 해당 레코드에 잠금을 걸어 
            # 동일 플레이어에 대한 동시 세션 생성/수정 시도를 방지합니다.
            # Player 모델이 없거나 잠금이 필요 없으면 이 부분을 제거하거나 수정해야 합니다.
            try:
                player_stmt = select(Player).where(Player.id == player_id).with_for_update(of=Player, key_share=True) # FOR NO KEY UPDATE
                await self.db.execute(player_stmt) # 잠금 실행
            except Exception as e:
                 # Player 테이블이 없거나 다른 문제 발생 시 로깅
                 logger.error(f"Failed to lock player {player_id} for session check: {e}")
                 # 잠금 실패 시 어떻게 처리할지 정책 필요 (예: 오류 발생 또는 잠금 없이 진행)
                 # 여기서는 잠금 없이 진행하도록 함 (또는 raise e)
                 pass 

        result = await self.db.execute(stmt)
        return result.scalars().first()
        
    async def create_session(self, session: GameSession) -> GameSession:
        """새 게임 세션을 데이터베이스에 저장합니다."""
        try:
            self.db.add(session)
            await self.db.flush() # DB에 보내지만 커밋은 안 함 (ID 등 생성)
            await self.db.refresh(session) # DB에서 생성된 값 로드
            logger.info(f"GameSession record created in DB: {session.id}")
            return session
        except Exception as e:
             # flush 또는 refresh 중 오류 발생 가능성
             logger.exception(f"Error during GameSession creation flush/refresh for player {session.player_id}: {e}")
             # 서비스 레이어에서 트랜잭션 롤백 처리
             raise

    async def get_session_by_token(self, token: str) -> Optional[GameSession]:
        """세션 토큰으로 게임 세션을 조회합니다."""
        stmt = select(GameSession).where(GameSession.token == token)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    # 필요한 다른 세션 관련 메서드 추가 (예: update_session_status 등) 