from fastapi import Query, Path, Depends
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta
import logging

from sqlalchemy.orm import Session
from backend.api.dependencies.db import get_db
from backend.api.dependencies.i18n import get_translator, Translator

logger = logging.getLogger(__name__)

async def common_pagination_params(
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(20, ge=1, le=100, description="페이지 크기")
) -> Dict[str, int]:
    """
    공통 페이지네이션 파라미터
    
    Args:
        page: 페이지 번호 (1부터 시작)
        page_size: 페이지 크기 (항목 수)
    
    Returns:
        Dict[str, int]: 페이지네이션 파라미터
    """
    return {
        "skip": (page - 1) * page_size,
        "limit": page_size,
        "page": page,
        "page_size": page_size
    }

async def common_sort_params(
    sort_by: Optional[str] = Query(None, description="정렬 필드"),
    sort_order: Optional[str] = Query("asc", description="정렬 방향 (asc, desc)")
) -> Dict[str, str]:
    """
    공통 정렬 파라미터
    
    Args:
        sort_by: 정렬 필드 이름
        sort_order: 정렬 방향 (asc 또는 desc)
    
    Returns:
        Dict[str, str]: 정렬 파라미터
    """
    return {
        "sort_by": sort_by,
        "sort_order": sort_order.lower() if sort_order else "asc"
    }

async def parse_date_range(
    start_date: Optional[date] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="종료 날짜 (YYYY-MM-DD)")
) -> Dict[str, Optional[date]]:
    """
    날짜 범위 파싱
    
    Args:
        start_date: 시작 날짜
        end_date: 종료 날짜
    
    Returns:
        Dict[str, Optional[date]]: 날짜 범위 정보
    """
    # 종료 날짜가 없으면 현재 날짜 사용
    if start_date and not end_date:
        end_date = date.today()
    
    # 시작 날짜가 없으면 종료 날짜에서 30일 전으로 설정
    if end_date and not start_date:
        start_date = end_date - timedelta(days=30)
    
    return {
        "start_date": start_date,
        "end_date": end_date
    }

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