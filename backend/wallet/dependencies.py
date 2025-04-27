from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from redis.asyncio import Redis
from typing import Union
import logging

# Import core dependencies
from backend.core.dependencies import get_db, get_redis_client

# Import wallet specific services and repositories
from backend.services.wallet.wallet_service import WalletService
from backend.repositories.wallet_repository import WalletRepository

# Import AML service
from backend.services.aml.aml_service import AMLService

logger = logging.getLogger(__name__)

async def get_wallet_service(
    session: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(get_redis_client)
) -> WalletService:
    """WalletService 인스턴스를 생성하고 반환하는 의존성 함수"""
    wallet_repo = WalletRepository(session=session)
    return WalletService(
        wallet_repo=wallet_repo,
        redis_client=redis_client
    )

async def get_aml_service(db: Union[AsyncSession, Session] = Depends(get_db)) -> AMLService:
    """
    Dependency function that creates an instance of the AMLService
    with a database session.
    """
    return AMLService(db=db) 