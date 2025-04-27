from fastapi import Query, Path, Depends
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta
import logging

from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from backend.api.dependencies.db import get_db
from backend.api.dependencies.i18n import get_translator, Translator

logger = logging.getLogger(__name__)

async def get_currency_param(
    currency: Optional[str] = Query(None, min_length=3, max_length=3, description="통화 코드"),
    db: Session = Depends(get_db)
) -> str:
    """
    통화 코드 파라미터 처리
    
    Args:
        currency: 통화 코드
        db: 데이터베이스 세션
    
    Returns:
        str: 유효한 통화 코드
    """
    from backend.services.wallet.currency_service import CurrencyService
    
    # 통화 서비스 초기화
    currency_service = CurrencyService(db)
    
    # 통화 코드가 제공되지 않은 경우 기본값 사용
    if not currency:
        return currency_service.get_default_currency()
    
    # 통화 코드 유효성 검증
    if not currency_service.is_valid_currency(currency):
        from backend.api.errors.exceptions import InvalidRequestException
        raise InvalidRequestException(f"Invalid currency code: {currency}")
    
    return currency.upper()

# get_partner_service has been moved to backend/partners/dependencies.py
# def get_partner_service(db: AsyncSession = Depends(get_db)) -> PartnerService:
#     """PartnerService 의존성 주입 함수"""
#     return PartnerService(db=db)

# 다른 서비스들도 필요하다면 여기에 추가...
# from backend.services.auth.auth_service import AuthService
# def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
#     return AuthService(db)