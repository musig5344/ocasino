"""
게임 리포지토리
게임, 게임 세션, 게임 설정 등 관련 데이터 액세스
"""
from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from backend.models.domain.game import Game, GameSession, GameTransaction, GameProvider

class GameRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_game_by_id(self, game_id: UUID) -> Optional[Game]:
        """ID로 게임 조회"""
        result = await self.session.execute(
            select(Game).where(Game.id == game_id)
        )
        return result.scalars().first()
    
    async def get_game_by_code(self, game_code: str, provider_code: str) -> Optional[Game]:
        """게임 코드와 제공자 코드로 게임 조회"""
        result = await self.session.execute(
            select(Game).join(GameProvider).where(
                Game.game_code == game_code,
                GameProvider.code == provider_code
            )
        )
        return result.scalars().first()
    
    async def list_games(
        self, 
        provider_id: Optional[UUID] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        offset: int = 0, 
        limit: int = 100
    ) -> List[Game]:
        """게임 목록 조회"""
        query = select(Game)
        
        if provider_id:
            query = query.where(Game.provider_id == provider_id)
        if category:
            query = query.where(Game.category == category)
        if status:
            query = query.where(Game.status == status)
        
        query = query.order_by(Game.name).offset(offset).limit(limit)
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def create_game(self, game: Game) -> Game:
        """새 게임 생성"""
        self.session.add(game)
        await self.session.flush()
        return game
    
    async def update_game(self, game: Game) -> Game:
        """게임 정보 업데이트"""
        self.session.add(game)
        await self.session.flush()
        return game
    
    async def get_provider_by_id(self, provider_id: UUID) -> Optional[GameProvider]:
        """ID로 게임 제공자 조회"""
        result = await self.session.execute(
            select(GameProvider).where(GameProvider.id == provider_id)
        )
        return result.scalars().first()
    
    async def get_provider_by_code(self, code: str) -> Optional[GameProvider]:
        """코드로 게임 제공자 조회"""
        result = await self.session.execute(
            select(GameProvider).where(GameProvider.code == code)
        )
        return result.scalars().first()
    
    async def list_providers(self, status: Optional[str] = None) -> List[GameProvider]:
        """게임 제공자 목록 조회"""
        query = select(GameProvider)
        
        if status:
            query = query.where(GameProvider.status == status)
        
        query = query.order_by(GameProvider.name)
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def create_provider(self, provider: GameProvider) -> GameProvider:
        """새 게임 제공자 생성"""
        self.session.add(provider)
        await self.session.flush()
        return provider
    
    async def update_provider(self, provider: GameProvider) -> GameProvider:
        """게임 제공자 정보 업데이트"""
        self.session.add(provider)
        await self.session.flush()
        return provider
    
    async def get_session(self, session_id: UUID) -> Optional[GameSession]:
        """ID로 게임 세션 조회"""
        result = await self.session.execute(
            select(GameSession).where(GameSession.id == session_id)
        )
        return result.scalars().first()
    
    async def get_active_session_by_token(self, token: str) -> Optional[GameSession]:
        """토큰으로 활성 게임 세션 조회"""
        result = await self.session.execute(
            select(GameSession).where(
                GameSession.token == token,
                GameSession.status == 'active'
            )
        )
        return result.scalars().first()
    
    async def create_session(self, session: GameSession) -> GameSession:
        """새 게임 세션 생성"""
        self.session.add(session)
        await self.session.flush()
        return session
    
    async def update_session(self, session: GameSession) -> GameSession:
        """게임 세션 정보 업데이트"""
        self.session.add(session)
        await self.session.flush()
        return session
    
    async def get_game_transaction(self, tx_id: UUID) -> Optional[GameTransaction]:
        """ID로 게임 트랜잭션 조회"""
        result = await self.session.execute(
            select(GameTransaction).where(GameTransaction.id == tx_id)
        )
        return result.scalars().first()
    
    async def get_game_transaction_by_reference(self, reference_id: str) -> Optional[GameTransaction]:
        """참조 ID로 게임 트랜잭션 조회"""
        result = await self.session.execute(
            select(GameTransaction).where(GameTransaction.reference_id == reference_id)
        )
        return result.scalars().first()
    
    async def create_game_transaction(self, transaction: GameTransaction) -> GameTransaction:
        """새 게임 트랜잭션 생성"""
        self.session.add(transaction)
        await self.session.flush()
        return transaction