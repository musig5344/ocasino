from fastapi import Query, Path, Depends
from typing import Optional, List, Dict
from datetime import datetime, date
from sqlalchemy.orm import Session

from backend.api.dependencies.db import get_db
from backend.i18n import Translator, get_translator

async def common_pagination_params(
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(20, ge=1, le=100, description="페이지 크기")
) -> dict:
    """
    공통 페이지네이션 파라미터
    
    Args:
        page: 페이지 번호 (1부터 시작)
        page_size: 페이지 크기 (항목 수)
    
    Returns:
        dict: 페이지네이션 파라미터
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
) -> dict:
    """
    공통 정렬 파라미터
    
    Args:
        sort_by: 정렬 필드 이름
        sort_order: 정렬 방향 (asc 또는 desc)
    
    Returns:
        dict: 정렬 파라미터
    """
    return {
        "sort_by": sort_by,
        "sort_order": sort_order.lower() if sort_order else "asc"
    }

async def parse_date_range(
    start_date: Optional[date] = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="종료 날짜 (YYYY-MM-DD)")
) -> dict:
    """
    날짜 범위 파싱
    
    Args:
        start_date: 시작 날짜
        end_date: 종료 날짜
    
    Returns:
        dict: 날짜 범위 정보
    """
    # 종료 날짜가 없으면 현재 날짜 사용
    if start_date and not end_date:
        end_date = date.today()
    
    return {
        "start_date": start_date,
        "end_date": end_date
    }