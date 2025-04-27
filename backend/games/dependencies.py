from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db  # Import from core dependencies
from backend.services.game.game_service import GameService
from backend.services.game.game_session_service import GameSessionService


# Dependency for GameService (specific to this module)
async def get_game_service(db: AsyncSession = Depends(get_db)) -> GameService:
    return GameService(db)


# Dependency for GameSessionService (specific to this module)
async def get_game_session_service(db: AsyncSession = Depends(get_db)) -> GameSessionService:
    return GameSessionService(db) 