from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db  # Import from core dependencies
from backend.partners.service import PartnerService

def get_partner_service(db: AsyncSession = Depends(get_db)) -> PartnerService:
    """PartnerService 의존성 주입 함수"""
    return PartnerService(db=db) 