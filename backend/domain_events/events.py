import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum

class DomainEventType(str, Enum):
    """도메인 이벤트 유형"""
    # 사용자 관련 이벤트
    USER_REGISTERED = "user.registered"
    USER_LOGGED_IN = "user.logged_in"
    USER_LOGGED_OUT = "user.logged_out"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    
    # 파트너 관련 이벤트
    PARTNER_CREATED = "partner.created"
    PARTNER_UPDATED = "partner.updated"
    PARTNER_STATUS_CHANGED = "partner.status_changed"
    API_KEY_CREATED = "partner.api_key_created"
    API_KEY_DEACTIVATED = "partner.api_key_deactivated"
    
    # 지갑 관련 이벤트
    WALLET_CREATED = "wallet.created"
    WALLET_BALANCE_CHANGED = "wallet.balance_changed"
    DEPOSIT_COMPLETED = "wallet.deposit_completed"
    WITHDRAWAL_COMPLETED = "wallet.withdrawal_completed"
    TRANSACTION_CANCELLED = "wallet.transaction_cancelled"
    
    # 게임 관련 이벤트
    GAME_SESSION_STARTED = "game.session_started"
    GAME_SESSION_ENDED = "game.session_ended"
    BET_PLACED = "game.bet_placed"
    WIN_CREDITED = "game.win_credited"
    GAME_ROUND_COMPLETED = "game.round_completed"
    
    # AML/KYC 관련 이벤트
    KYC_SUBMITTED = "kyc.submitted"
    KYC_APPROVED = "kyc.approved"
    KYC_REJECTED = "kyc.rejected"
    AML_ALERT_CREATED = "aml.alert_created"
    AML_REPORT_SUBMITTED = "aml.report_submitted"
    
    # 시스템 이벤트
    SYSTEM_ERROR = "system.error"
    SECURITY_VIOLATION = "system.security_violation"
    API_RATE_LIMIT_EXCEEDED = "system.api_rate_limit_exceeded"

class DomainEvent:
    """도메인 이벤트 클래스"""
    
    def __init__(
        self, 
        event_type: DomainEventType,
        aggregate_id: str,
        data: Dict[str, Any],
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        도메인 이벤트 초기화
        
        Args:
            event_type: 이벤트 유형
            aggregate_id: 이벤트가 관련된 집합체 ID (예: player_id, transaction_id)
            data: 이벤트 데이터
            user_id: 이벤트를 발생시킨 사용자 ID (선택 사항)
            metadata: 추가 메타데이터 (선택 사항)
        """
        self.event_id = str(uuid.uuid4())
        self.event_type = event_type
        self.aggregate_id = aggregate_id
        self.data = data
        self.user_id = user_id
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow().isoformat()
        self.version = "1.0"  # 이벤트 스키마 버전
    
    def to_dict(self) -> Dict[str, Any]:
        """이벤트를 딕셔너리로 직렬화"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "aggregate_id": self.aggregate_id,
            "data": self.data,
            "user_id": self.user_id,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "version": self.version
        }
    
    def __str__(self) -> str:
        """이벤트의 문자열 표현"""
        return f"{self.event_type}:{self.aggregate_id} at {self.timestamp}"
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DomainEvent':
        """딕셔너리에서 이벤트 객체 생성"""
        event = cls(
            event_type=data["event_type"],
            aggregate_id=data["aggregate_id"],
            data=data["data"],
            user_id=data.get("user_id"),
            metadata=data.get("metadata", {})
        )
        event.event_id = data["event_id"]
        event.timestamp = data["timestamp"]
        event.version = data.get("version", "1.0")
        return event

# --- Wallet / Transaction Specific Events ---

class TransactionCompletedEvent(DomainEvent):
    """트랜잭션 완료 이벤트"""
    def __init__(
        self,
        transaction_id: Any,
        player_id: Any,
        partner_id: Any,
        amount: Any,
        currency: str,
        transaction_type: str, # Expecting the string value of TransactionType enum
        timestamp: datetime,
        original_reference_id: Optional[str] = None, # For rollbacks
        **kwargs # Allow additional data
    ):
        # Import TransactionType locally if not available globally
        # This is generally not recommended, prefer module-level imports
        # but useful if TransactionType cannot be imported at the top level easily
        try:
            # Attempt to import TransactionType enum
            from backend.models.domain.wallet import TransactionType
            # Determine the specific DomainEventType based on the transaction_type string
            event_type = DomainEventType.TRANSACTION_CANCELLED # Default or fallback?
            if transaction_type == TransactionType.BET.value:
                 event_type = DomainEventType.BET_PLACED
            elif transaction_type == TransactionType.WIN.value:
                 event_type = DomainEventType.WIN_CREDITED
            elif transaction_type == TransactionType.DEPOSIT.value:
                 event_type = DomainEventType.DEPOSIT_COMPLETED
            elif transaction_type == TransactionType.WITHDRAWAL.value:
                event_type = DomainEventType.WITHDRAWAL_COMPLETED
            elif transaction_type == TransactionType.REFUND.value:
                 # Use TRANSACTION_CANCELLED as defined in the enum
                 event_type = DomainEventType.TRANSACTION_CANCELLED
            # Add handling for other transaction types if necessary
            # else:
            #    logger.warning(f"Unhandled transaction type '{transaction_type}' for event mapping.")
        except ImportError:
             # Fallback if TransactionType cannot be imported
             # This assumes simple string matching will suffice
             print("Warning: Could not import TransactionType enum in TransactionCompletedEvent. Using string matching for event type.")
             if transaction_type == 'bet': event_type = DomainEventType.BET_PLACED
             elif transaction_type == 'win': event_type = DomainEventType.WIN_CREDITED
             elif transaction_type == 'deposit': event_type = DomainEventType.DEPOSIT_COMPLETED
             elif transaction_type == 'withdrawal': event_type = DomainEventType.WITHDRAWAL_COMPLETED
             elif transaction_type == 'refund': event_type = DomainEventType.TRANSACTION_CANCELLED
             else: event_type = DomainEventType.TRANSACTION_CANCELLED # Fallback

        data = {
            "transaction_id": str(transaction_id),
            "player_id": str(player_id),
            "partner_id": str(partner_id),
            "amount": str(amount),
            "currency": currency,
            "transaction_type": transaction_type, # Store the original string type
            "timestamp": timestamp.isoformat(), # Use ISO format string
            **kwargs # Include any extra data passed
        }
        if original_reference_id:
             data["original_reference_id"] = original_reference_id

        super().__init__(
            event_type=event_type,
            aggregate_id=str(transaction_id), # Use transaction_id as aggregate ID
            data=data,
            user_id=str(player_id) # Assume player_id is the relevant user ID
        )

class WalletBalanceChangedEvent(DomainEvent):
    """지갑 잔액 변경 이벤트"""
    def __init__(
        self,
        wallet_id: Any,
        player_id: Any,
        partner_id: Any,
        new_balance: Any,
        currency: str,
        timestamp: datetime,
        **kwargs
    ):
        data = {
            "wallet_id": str(wallet_id),
            "player_id": str(player_id),
            "partner_id": str(partner_id),
            "new_balance": str(new_balance), # Store balance as string for consistency?
            "currency": currency,
            "timestamp": timestamp.isoformat(),
            **kwargs
        }
        super().__init__(
            event_type=DomainEventType.WALLET_BALANCE_CHANGED,
            aggregate_id=str(wallet_id), # Use wallet_id as aggregate ID
            data=data,
            user_id=str(player_id)
        )