"""
요청 컨텍스트 관련 유틸리티
"""
import contextvars
from typing import Any, Optional

# 요청별 데이터를 저장하기 위한 ContextVar 정의 (예시)
# 실제 사용 방식은 미들웨어 구현에 따라 달라질 수 있습니다.
_request_scope_context: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "request_scope_context", default=None
)

def set_request_context(context: dict) -> None:
    """현재 요청 컨텍스트 설정"""
    _request_scope_context.set(context)

def get_request_context() -> Optional[dict]:
    """현재 요청 컨텍스트 가져오기"""
    return _request_scope_context.get()

def clear_request_context() -> None:
    """현재 요청 컨텍스트 초기화"""
    _request_scope_context.set(None)

def get_request_attribute(key: str, default: Any = None) -> Any:
    """요청 컨텍스트에서 특정 속성 가져오기"""
    context = get_request_context()
    if context:
        return context.get(key, default)
    return default

def set_request_attribute(key: str, value: Any) -> None:
    """요청 컨텍스트에 특정 속성 설정"""
    context = get_request_context()
    if context is None:
        context = {}
        set_request_context(context)
    context[key] = value 