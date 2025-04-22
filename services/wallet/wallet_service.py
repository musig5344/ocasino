"""
지갑 서비스
트랜잭션 처리, 잔액 관리 등 비즈니스 로직 담당
"""
import logging
from uuid import UUID, uuid4
from decimal import Decimal
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import uuid
import json

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from backend.models.domain.wallet import Wallet, Transaction, TransactionType, TransactionStatus
from backend.models.domain.partner import Partner
from backend.repositories.wallet_repository import WalletRepository
from backend.repositories.partner_repository import PartnerRepository
from backend.schemas.wallet import (
    WalletCreate, DebitRequest, CreditRequest, 
    RollbackRequest, BalanceResponse, TransactionResponse
)
from backend.cache.redis_cache import get_redis_client
from backend.domain_events import publish_event, DomainEventType
from backend.core.exceptions import (
    InsufficientFundsError, DuplicateTransactionError, 
    WalletNotFoundError, CurrencyMismatchError,
    TransactionNotFoundError, ValidationError
)

logger = logging.getLogger(__name__)

class WalletService:
    """지갑 서비스"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.wallet_repo = WalletRepository(db)
        self.partner_repo = PartnerRepository(db)
        self.redis = get_redis_client()
    
    async def get_wallet(self, player_id: UUID, partner_id: UUID) -> Optional[Wallet]:
        """
        플레이어 지갑 조회
        
        Args:
            player_id: 플레이어 ID
            partner_id: 파트너 ID
            
        Returns:
            Optional[Wallet]: 지갑 객체 또는 None
        """
        # 캐시 확인
        cache_key = f"wallet:{player_id}:{partner_id}"
        cached_data = await self.redis.get(cache_key)
        
        if cached_data:
            cached_wallet = json.loads(cached_data)
            # 객체 변환 없이 캐시 데이터 바로 사용 가능
            return Wallet(
                id=UUID(cached_wallet["id"]),
                player_id=UUID(cached_wallet["player_id"]),
                partner_id=UUID(cached_wallet["partner_id"]),
                balance=Decimal(cached_wallet["balance"]),
                currency=cached_wallet["currency"],
                is_active=cached_wallet["is_active"],
                is_locked=cached_wallet["is_locked"]
            )
        
        # DB 조회
        wallet = await self.wallet_repo.get_player_wallet(player_id, partner_id)
        
        # 캐시 저장
        if wallet:
            await self.redis.set(
                cache_key,
                json.dumps({
                    "id": str(wallet.id),
                    "player_id": str(wallet.player_id),
                    "partner_id": str(wallet.partner_id),
                    "balance": str(wallet.balance),
                    "currency": wallet.currency,
                    "is_active": wallet.is_active,
                    "is_locked": wallet.is_locked
                }),
                ex=60  # 60초 만료
            )
        
        return wallet
    
    async def create_wallet(self, player_id: UUID, partner_id: UUID, currency: str) -> Wallet:
        """
        새 지갑 생성
        
        Args:
            player_id: 플레이어 ID
            partner_id: 파트너 ID
            currency: 통화 코드
            
        Returns:
            Wallet: 생성된 지갑
            
        Raises:
            HTTPException: 파트너가 존재하지 않는 경우
        """
        # 파트너 존재 확인
        partner = await self.partner_repo.get_partner_by_id(partner_id)
        if not partner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Partner {partner_id} not found"
            )
        
        # 지갑 생성
        wallet = Wallet(
            player_id=player_id,
            partner_id=partner_id,
            balance=Decimal("0"),
            currency=currency,
            is_active=True,
            is_locked=False
        )
        
        created_wallet = await self.wallet_repo.create_wallet(wallet)
        logger.info(f"Created new wallet for player {player_id}, partner {partner_id}")
        
        # 캐시 무효화
        await self.invalidate_wallet_cache(player_id, partner_id)
        
        return created_wallet
    
    async def ensure_wallet_exists(
        self, player_id: UUID, partner_id: UUID, currency: str
    ) -> Tuple[Wallet, bool]:
        """
        지갑 존재 확인 및 필요 시 생성
        
        Args:
            player_id: 플레이어 ID
            partner_id: 파트너 ID
            currency: 통화 코드
            
        Returns:
            Tuple[Wallet, bool]: (지갑 객체, 신규 생성 여부)
        """
        wallet = await self.get_wallet(player_id, partner_id)
        created = False
        
        if not wallet:
            wallet = await self.create_wallet(player_id, partner_id, currency)
            created = True
        elif wallet.currency != currency:
            raise CurrencyMismatchError(
                f"Wallet currency mismatch: expected {currency}, got {wallet.currency}"
            )
        
        return wallet, created
    
    async def get_balance(
        self, player_id: UUID, partner_id: UUID, reference_id: str
    ) -> BalanceResponse:
        """
        플레이어 잔액 조회
        
        Args:
            player_id: 플레이어 ID
            partner_id: 파트너 ID
            reference_id: 참조 ID
            
        Returns:
            BalanceResponse: 잔액 응답
            
        Raises:
            WalletNotFoundError: 지갑이 존재하지 않는 경우
        """
        wallet = await self.get_wallet(player_id, partner_id)
        
        if not wallet:
            raise WalletNotFoundError(f"Wallet not found for player {player_id}")
        
        if not wallet.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wallet is not active"
            )
        
        return BalanceResponse(
            player_id=player_id,
            balance=wallet.balance,
            currency=wallet.currency,
            reference_id=reference_id,
            timestamp=datetime.utcnow()
        )
    
    async def debit(self, request: DebitRequest, partner_id: UUID) -> TransactionResponse:
        """
        지갑에서 금액 차감 (베팅 등)
        
        Args:
            request: 차감 요청
            partner_id: 파트너 ID
            
        Returns:
            TransactionResponse: 트랜잭션 응답
            
        Raises:
            DuplicateTransactionError: 중복 트랜잭션
            WalletNotFoundError: 지갑이 존재하지 않는 경우
            InsufficientFundsError: 잔액 부족
        """
        # 트랜잭션 중복 확인 (멱등성 보장)
        existing_tx = await self.wallet_repo.get_transaction_by_reference(request.reference_id)
        if existing_tx:
            if existing_tx.transaction_type == TransactionType.BET:
                # 동일 트랜잭션 ID로 이미 처리됨
                return TransactionResponse(
                    player_id=existing_tx.player_id,
                    reference_id=existing_tx.reference_id,
                    transaction_type=existing_tx.transaction_type,
                    amount=existing_tx.amount,
                    currency=existing_tx.currency,
                    status=existing_tx.status,
                    balance=existing_tx.updated_balance,
                    timestamp=existing_tx.created_at
                )
            else:
                # 다른 유형의 트랜잭션으로 이미 사용된 참조 ID
                raise DuplicateTransactionError(
                    f"Transaction reference {request.reference_id} already exists with type {existing_tx.transaction_type}"
                )
        
        # 지갑 조회 (with for_update)
        wallet = await self.wallet_repo.get_player_wallet(
            request.player_id, partner_id, for_update=True
        )
        
        if not wallet:
            raise WalletNotFoundError(f"Wallet not found for player {request.player_id}")
        
        if not wallet.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wallet is not active"
            )
        
        if wallet.is_locked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wallet is locked"
            )
        
        # 통화 확인
        if wallet.currency != request.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: wallet {wallet.currency}, request {request.currency}"
            )
        
        # 잔액 확인
        if wallet.balance < request.amount:
            raise InsufficientFundsError(
                f"Insufficient funds: balance {wallet.balance}, requested {request.amount}"
            )
        
        # 원래 잔액 저장
        original_balance = wallet.balance
        
        # 잔액 차감
        wallet.balance -= request.amount
        
        # 트랜잭션 생성
        transaction = Transaction(
            id=uuid4(),
            reference_id=request.reference_id,
            wallet_id=wallet.id,
            player_id=request.player_id,
            partner_id=partner_id,
            transaction_type=TransactionType.BET,
            amount=request.amount,
            currency=request.currency,
            status=TransactionStatus.COMPLETED,
            original_balance=original_balance,
            updated_balance=wallet.balance,
            game_id=request.game_id,
            game_session_id=request.game_session_id,
            metadata=request.metadata
        )
        
        # 트랜잭션 저장
        await self.wallet_repo.create_transaction(transaction)
        
        # 캐시 무효화
        await self.invalidate_wallet_cache(request.player_id, partner_id)
        
        # 이벤트 발행
        await self._publish_transaction_event(transaction)
        
        return TransactionResponse(
            player_id=transaction.player_id,
            reference_id=transaction.reference_id,
            transaction_type=transaction.transaction_type,
            amount=transaction.amount,
            currency=transaction.currency,
            status=transaction.status,
            balance=transaction.updated_balance,
            timestamp=transaction.created_at
        )
    
    async def credit(self, request: CreditRequest, partner_id: UUID) -> TransactionResponse:
        """
        지갑에 금액 추가 (승리 등)
        
        Args:
            request: 추가 요청
            partner_id: 파트너 ID
            
        Returns:
            TransactionResponse: 트랜잭션 응답
            
        Raises:
            DuplicateTransactionError: 중복 트랜잭션
        """
        # 트랜잭션 중복 확인 (멱등성 보장)
        existing_tx = await self.wallet_repo.get_transaction_by_reference(request.reference_id)
        if existing_tx:
            if existing_tx.transaction_type == TransactionType.WIN:
                # 동일 트랜잭션 ID로 이미 처리됨 (멱등성)
                return TransactionResponse(
                    player_id=existing_tx.player_id,
                    reference_id=existing_tx.reference_id,
                    transaction_type=existing_tx.transaction_type,
                    amount=existing_tx.amount,
                    currency=existing_tx.currency,
                    status=existing_tx.status,
                    balance=existing_tx.updated_balance,
                    timestamp=existing_tx.created_at
                )
            else:
                # 다른 유형의 트랜잭션으로 이미 사용된 참조 ID
                raise DuplicateTransactionError(
                    f"Transaction reference {request.reference_id} already exists with type {existing_tx.transaction_type}"
                )
        
        # 지갑 확보 (없으면 생성)
        wallet, created = await self.ensure_wallet_exists(
            request.player_id, partner_id, request.currency
        )
        
        if not wallet.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wallet is not active"
            )
        
        if wallet.is_locked:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wallet is locked"
            )
        
        # 통화 확인
        if wallet.currency != request.currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: wallet {wallet.currency}, request {request.currency}"
            )
        
        # 원래 잔액 저장
        original_balance = wallet.balance
        
        # 잔액 증가
        wallet.balance += request.amount
        
        # 트랜잭션 생성
        transaction = Transaction(
            id=uuid4(),
            reference_id=request.reference_id,
            wallet_id=wallet.id,
            player_id=request.player_id,
            partner_id=partner_id,
            transaction_type=TransactionType.WIN,
            amount=request.amount,
            currency=request.currency,
            status=TransactionStatus.COMPLETED,
            original_balance=original_balance,
            updated_balance=wallet.balance,
            game_id=request.game_id,
            game_session_id=request.game_session_id,
            metadata=request.metadata
        )
        
        # 트랜잭션 저장
        await self.wallet_repo.create_transaction(transaction)
        
        # 캐시 무효화
        await self.invalidate_wallet_cache(request.player_id, partner_id)
        
        # 이벤트 발행
        await self._publish_transaction_event(transaction)
        
        return TransactionResponse(
            player_id=transaction.player_id,
            reference_id=transaction.reference_id,
            transaction_type=transaction.transaction_type,
            amount=transaction.amount,
            currency=transaction.currency,
            status=transaction.status,
            balance=transaction.updated_balance,
            timestamp=transaction.created_at
        )
    
    async def rollback(self, request: RollbackRequest, partner_id: UUID) -> TransactionResponse:
        """
        트랜잭션 롤백 (취소)
        
        Args:
            request: 롤백 요청
            partner_id: 파트너 ID
            
        Returns:
            TransactionResponse: 트랜잭션 응답
            
        Raises:
            DuplicateTransactionError: 중복 트랜잭션
            TransactionNotFoundError: 원본 트랜잭션이 존재하지 않는 경우
        """
        # 롤백 트랜잭션 중복 확인 (멱등성 보장)
        existing_rollback = await self.wallet_repo.get_transaction_by_reference(request.reference_id)
        if existing_rollback:
            if existing_rollback.transaction_type == TransactionType.REFUND:
                # 동일 트랜잭션 ID로 이미 처리됨 (멱등성)
                return TransactionResponse(
                    player_id=existing_rollback.player_id,
                    reference_id=existing_rollback.reference_id,
                    transaction_type=existing_rollback.transaction_type,
                    amount=existing_rollback.amount,
                    currency=existing_rollback.currency,
                    status=existing_rollback.status,
                    balance=existing_rollback.updated_balance,
                    timestamp=existing_rollback.created_at
                )
            else:
                # 다른 유형의 트랜잭션으로 이미 사용된 참조 ID
                raise DuplicateTransactionError(
                    f"Transaction reference {request.reference_id} already exists with type {existing_rollback.transaction_type}"
                )
        
        # 원본 트랜잭션 조회
        original_tx = await self.wallet_repo.get_transaction_by_reference(request.original_reference_id)
        if not original_tx:
            raise TransactionNotFoundError(
                f"Original transaction {request.original_reference_id} not found"
            )
        
        # 이미 롤백 되었는지 확인
        if original_tx.status == TransactionStatus.CANCELED:
            raise ValidationError(f"Transaction {request.original_reference_id} already canceled")
        
        # 지갑 조회
        wallet = await self.wallet_repo.get_player_wallet(
            request.player_id, partner_id, for_update=True
        )
        
        if not wallet:
            raise WalletNotFoundError(f"Wallet not found for player {request.player_id}")
        
        # 원래 잔액 저장
        original_balance = wallet.balance
        
        # 트랜잭션 유형에 따라 잔액 조정
        if original_tx.transaction_type == TransactionType.BET:
            # 베팅 롤백 = 잔액 증가
            wallet.balance += original_tx.amount
        elif original_tx.transaction_type == TransactionType.WIN:
            # 승리 롤백 = 잔액 감소
            if wallet.balance < original_tx.amount:
                raise InsufficientFundsError(
                    f"Insufficient funds for rollback: balance {wallet.balance}, required {original_tx.amount}"
                )
            wallet.balance -= original_tx.amount
        
        # 원본 트랜잭션 상태 업데이트
        original_tx.status = TransactionStatus.CANCELED
        
        # 롤백 트랜잭션 생성
        rollback_tx = Transaction(
            id=uuid4(),
            reference_id=request.reference_id,
            wallet_id=wallet.id,
            player_id=request.player_id,
            partner_id=partner_id,
            transaction_type=TransactionType.REFUND,
            amount=original_tx.amount,
            currency=original_tx.currency,
            status=TransactionStatus.COMPLETED,
            original_balance=original_balance,
            updated_balance=wallet.balance,
            game_id=original_tx.game_id,
            game_session_id=original_tx.game_session_id,
            reference_transaction_id=original_tx.id,
            metadata={
                "original_transaction_type": original_tx.transaction_type,
                "original_reference_id": original_tx.reference_id
            }
        )
        
        # 트랜잭션 저장
        await self.wallet_repo.create_transaction(rollback_tx)
        
        # 캐시 무효화
        await self.invalidate_wallet_cache(request.player_id, partner_id)
        
        # 이벤트 발행
        await self._publish_transaction_event(rollback_tx)
        
        return TransactionResponse(
            player_id=rollback_tx.player_id,
            reference_id=rollback_tx.reference_id,
            transaction_type=rollback_tx.transaction_type,
            amount=rollback_tx.amount,
            currency=rollback_tx.currency,
            status=rollback_tx.status,
            balance=rollback_tx.updated_balance,
            timestamp=rollback_tx.created_at
        )
    
    async def get_player_transactions(
        self,
        player_id: UUID,
        partner_id: UUID,
        tx_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 100
    ) -> List[Transaction]:
        """
        플레이어 트랜잭션 내역 조회
        
        Args:
            player_id: 플레이어 ID
            partner_id: 파트너 ID
            tx_type: 트랜잭션 유형 필터
            start_date: 시작 날짜
            end_date: 종료 날짜
            offset: 페이징 오프셋
            limit: 페이징 제한
            
        Returns:
            List[Transaction]: 트랜잭션 목록
        """
        return await self.wallet_repo.get_player_transactions(
            player_id, partner_id, tx_type, start_date, end_date, offset, limit
        )
    
    async def invalidate_wallet_cache(self, player_id: UUID, partner_id: UUID) -> None:
        """
        지갑 캐시 무효화
        
        Args:
            player_id: 플레이어 ID
            partner_id: 파트너 ID
        """
        cache_key = f"wallet:{player_id}:{partner_id}"
        await self.redis.delete(cache_key)
    
    async def _publish_transaction_event(self, transaction: Transaction) -> None:
        """
        트랜잭션 이벤트 발행
        
        Args:
            transaction: 트랜잭션 객체
        """
        event_type_map = {
            TransactionType.BET: DomainEventType.BET_PLACED,
            TransactionType.WIN: DomainEventType.WIN_CREDITED,
            TransactionType.DEPOSIT: DomainEventType.DEPOSIT_COMPLETED,
            TransactionType.WITHDRAWAL: DomainEventType.WITHDRAWAL_COMPLETED,
            TransactionType.REFUND: DomainEventType.TRANSACTION_CANCELLED
        }
        
        event_type = event_type_map.get(transaction.transaction_type)
        if not event_type:
            return
        
        event_data = {
            "transaction_id": str(transaction.id),
            "reference_id": transaction.reference_id,
            "player_id": str(transaction.player_id),
            "wallet_id": str(transaction.wallet_id),
            "partner_id": str(transaction.partner_id),
            "type": transaction.transaction_type,
            "amount": str(transaction.amount),
            "currency": transaction.currency,
            "status": transaction.status,
            "balance": str(transaction.updated_balance),
            "created_at": transaction.created_at.isoformat()
        }
        
        if transaction.game_id:
            event_data["game_id"] = str(transaction.game_id)
        
        if transaction.game_session_id:
            event_data["game_session_id"] = str(transaction.game_session_id)
        
        await publish_event(
            event_type=event_type,
            aggregate_id=str(transaction.id),
            data=event_data,
            user_id=str(transaction.player_id),
            metadata={"partner_id": str(transaction.partner_id)}
        )