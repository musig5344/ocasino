import logging
from typing import Callable, Dict, List
from backend.domain_events.events import DomainEventType

logger = logging.getLogger(__name__)

# 이벤트 핸들러 저장소
_event_handlers: Dict[DomainEventType, List[Callable]] = {}
_global_handlers: List[Callable] = []

def subscribe(event_type: DomainEventType, handler: Callable) -> None:
    """
    이벤트 핸들러 등록
    
    Args:
        event_type: 구독할 이벤트 유형
        handler: 이벤트 처리 함수
    """
    if event_type not in _event_handlers:
        _event_handlers[event_type] = []
    
    if handler not in _event_handlers[event_type]:
        _event_handlers[event_type].append(handler)
        logger.debug(f"Subscribed handler to event type: {event_type}")

def subscribe_to_all(handler: Callable) -> None:
    """
    모든 이벤트에 대한 핸들러 등록
    
    Args:
        handler: 이벤트 처리 함수
    """
    if handler not in _global_handlers:
        _global_handlers.append(handler)
        logger.debug("Subscribed handler to all events")

def unsubscribe(event_type: DomainEventType, handler: Callable) -> None:
    """
    이벤트 핸들러 제거
    
    Args:
        event_type: 이벤트 유형
        handler: 제거할 이벤트 처리 함수
    """
    if event_type in _event_handlers and handler in _event_handlers[event_type]:
        _event_handlers[event_type].remove(handler)
        logger.debug(f"Unsubscribed handler from event type: {event_type}")

def unsubscribe_from_all(handler: Callable) -> None:
    """
    모든 이벤트에서 핸들러 제거
    
    Args:
        handler: 제거할 이벤트 처리 함수
    """
    if handler in _global_handlers:
        _global_handlers.remove(handler)
        logger.debug("Unsubscribed handler from all events")

def get_event_handlers(event_type: DomainEventType) -> List[Callable]:
    """이벤트 유형에 맞는 핸들러 목록 반환"""
    return _event_handlers.get(event_type, [])

def get_global_handlers() -> List[Callable]:
    """모든 글로벌 핸들러 목록 반환"""
    return _global_handlers 