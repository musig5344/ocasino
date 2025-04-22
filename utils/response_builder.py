from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from fastapi.responses import JSONResponse
from pydantic import BaseModel

def success_response(
    data: Any = None,
    message: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    status_code: int = 200
) -> JSONResponse:
    """성공 응답 생성"""
    response = {"status": "success"}
    
    if data is not None:
        # Pydantic 모델 처리
        if isinstance(data, BaseModel):
            response["data"] = data.dict()
        # Pydantic 모델 리스트 처리
        elif isinstance(data, list) and all(isinstance(item, BaseModel) for item in data):
            response["data"] = [item.dict() for item in data]
        else:
            response["data"] = data
    
    if message:
        response["message"] = message
    
    if meta:
        response["meta"] = meta
    
    # 타임스탬프 추가
    response["timestamp"] = datetime.utcnow().isoformat()
    
    return JSONResponse(
        content=response,
        status_code=status_code
    )

def paginated_response(
    items: List[Any],
    total: int,
    page: int,
    page_size: int,
    message: Optional[str] = None,
    additional_meta: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    """페이지네이션 응답 생성"""
    # 페이지네이션 메타데이터 계산
    total_pages = (total + page_size - 1) // page_size  # 올림 연산
    
    meta = {
        "page": page,
        "page_size": page_size,
        "total_items": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1
    }
    
    # 추가 메타데이터 병합
    if additional_meta:
        meta.update(additional_meta)
    
    # 아이템 처리
    processed_items = items
    if items and all(isinstance(item, BaseModel) for item in items):
        processed_items = [item.dict() for item in items]
    
    return success_response(
        data=processed_items,
        message=message,
        meta=meta
    )

def error_response(
    error_code: str,
    message: str,
    details: Optional[Any] = None,
    status_code: int = 400
) -> JSONResponse:
    """오류 응답 생성"""
    response = {
        "status": "error",
        "error": {
            "code": error_code,
            "message": message
        },
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if details:
        response["error"]["details"] = details
    
    return JSONResponse(
        content=response,
        status_code=status_code
    )