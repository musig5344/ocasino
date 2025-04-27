"""
도메인 이벤트 시스템
비즈니스 도메인 내에서 발생하는 중요 이벤트를 처리하는 메커니즘
"""
import logging
from typing import Callable, Dict, List, Any, Optional
from uuid import UUID

from backend.domain_events.events import DomainEvent, DomainEventType
from backend.domain_events.handlers import register_event_handlers
from backend.domain_events.registry import get_event_handlers, get_global_handlers

logger = logging.getLogger(__name__)

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
    
    # 글로벌 핸들러 호출 (registry 사용)
    for handler in get_global_handlers():
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Error in global handler for event {event.event_id}: {e}", exc_info=True)
    
    # 이벤트 유형별 핸들러 호출 (registry 사용)
    handlers = get_event_handlers(event.event_type)
    for handler in handlers:
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Error in handler for event {event.event_id} ({event.event_type}): {e}", exc_info=True)
    
    logger.debug(f"Published event: {event.event_type} (id: {event.event_id})")
    return event