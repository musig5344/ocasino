"""
도메인 이벤트 시스템
비즈니스 도메인 내에서 발생하는 중요 이벤트를 처리하는 메커니즘
"""
import logging
from typing import Callable, Dict, List, Any, Optional
from uuid import UUID

from backend.domain_events.events import DomainEvent, DomainEventType
from backend.domain_events.handlers import (
    register_event_handlers, handle_transaction_events, 
    handle_game_events, handle_user_events, handle_aml_events
)

logger = logging.getLogger(__name__)

# 이벤트 핸들러 저장소
_event_handlers: Dict[DomainEventType, List[Callable]] = {}
_global_handlers: List[Callable] = []

def initialize_event_system():
    """이벤트 시스템 초기화 및 핸들러 등록"""
    logger.info("Initializing domain event system")
    register_event_handlers()
    logger.info("Domain event handlers registered successfully")

async def publish_event(
    event_type: DomainEventType,
    aggregate_id: str,
    data: Dict[str, Any],
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> DomainEvent:
    """
    도메인 이벤트 발행
    
    Args:
        event_type: 이벤트 유형
        aggregate_id: 이벤트가 관련된 집합체 ID
        data: 이벤트 데이터
        user_id: 이벤트를 발생시킨 사용자 ID (선택 사항)
        metadata: 추가 메타데이터 (선택 사항)
        
    Returns:
        DomainEvent: 발행된 이벤트 객체
    """
    # 이벤트 객체 생성
    event = DomainEvent(
        event_type=event_type,
        aggregate_id=aggregate_id,
        data=data,
        user_id=user_id,
        metadata=metadata or {}
    )
    
    # 글로벌 핸들러 호출
    for handler in _global_handlers:
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Error in global handler for event {event.event_id}: {e}", exc_info=True)
    
    # 이벤트 유형별 핸들러 호출
    handlers = _event_handlers.get(event_type, [])
    for handler in handlers:
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Error in handler for event {event.event_id} ({event_type}): {e}", exc_info=True)
    
    logger.debug(f"Published event: {event_type} (id: {event.event_id})")
    return event

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