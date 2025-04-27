"""
지갑 데이터 접근 로직 (Repository)
"""
import logging
from typing import Optional, List, Dict, Any
from uuid import UUID
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select # select 임포트
from sqlalchemy.orm import selectinload # selectinload 임포트
from sqlalchemy import update # update 임포트 추가

# 모델 임포트 (경로 확인 필요)
from backend.models.domain.wallet import Wallet, Transaction, TransactionStatus, TransactionType # TransactionStatus 임포트 추가

logger = logging.getLogger(__name__)

class WalletRepository:
    """지갑 관련 데이터베이스 작업을 처리합니다."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        
    async def get_wallet_by_player_id(self, player_id: UUID, partner_id: UUID, for_update: bool = False) -> Optional[Wallet]:
        """플레이어 ID와 파트너 ID로 지갑 정보를 조회합니다.

        Args:
            player_id: 플레이어 ID
            partner_id: 파트너 ID
            for_update: SELECT ... FOR UPDATE 잠금을 사용할지 여부
        """
        # 실제 구현
        stmt = select(Wallet).where(
            Wallet.player_id == player_id,
            Wallet.partner_id == partner_id
        )
        if for_update:
            # PESSIMISTIC WRITE 잠금 사용 (PostgreSQL 기준)
            # 다른 DB는 문법이 다를 수 있음
            stmt = stmt.with_for_update()
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_player_wallet(self, player_id: UUID, partner_id: UUID, for_update: bool = False) -> Optional[Wallet]:
        """get_wallet_by_player_id의 별칭입니다. 테스트 코드 호환성을 위해 추가합니다."""
        return await self.get_wallet_by_player_id(player_id, partner_id, for_update=for_update)
        
    async def create_transaction(self, transaction: Transaction) -> Transaction:
        """새 트랜잭션을 생성합니다."""
        # 실제 구현 필요
        self.session.add(transaction)
        await self.session.flush()
        await self.session.refresh(transaction)
        logger.warning(f"WalletRepository.create_transaction is not fully implemented.")
        return transaction

    async def get_transaction_by_reference(self, reference_id: str, partner_id: UUID) -> Optional[Transaction]:
        """트랜잭션 참조 ID와 파트너 ID로 트랜잭션 정보를 조회합니다."""
        # 실제 데이터베이스 조회 로직 구현
        query = select(Transaction).where(
            Transaction.reference_id == reference_id,
            Transaction.partner_id == partner_id
        )
        result = await self.session.execute(query)
        transaction = result.scalar_one_or_none()
        if transaction:
            logger.debug(f"Transaction found for ref: {reference_id}, partner: {partner_id}")
        else:
            logger.debug(f"Transaction not found for ref: {reference_id}, partner: {partner_id}")
        return transaction

    async def get_rollback_transaction(self, original_transaction_id: UUID) -> Optional[Transaction]:
        """원본 트랜잭션 ID로 롤백 트랜잭션을 조회합니다.

        Args:
            original_transaction_id: 롤백된 원본 트랜잭션의 ID

        Returns:
            롤백 트랜잭션 객체 또는 None
        """
        stmt = select(Transaction).where(
            Transaction.original_transaction_id == original_transaction_id,
            Transaction.transaction_type == TransactionType.ROLLBACK # TransactionType 임포트 필요
        )
        result = await self.session.execute(stmt)
        rollback_tx = result.scalar_one_or_none()
        if rollback_tx:
            logger.debug(f"Rollback transaction found for original tx: {original_transaction_id}")
        else:
            logger.debug(f"No rollback transaction found for original tx: {original_transaction_id}")
        return rollback_tx

    async def update_transaction_status(self, transaction_id: UUID, new_status: TransactionStatus) -> None:
        """트랜잭션 상태 업데이트

        Args:
            transaction_id: 업데이트할 트랜잭션 ID
            new_status: 새로운 트랜잭션 상태
        """
        stmt = (
            update(Transaction)
            .where(Transaction.id == transaction_id)
            .values(status=new_status)
        )
        result = await self.session.execute(stmt)
        if result.rowcount == 0:
             logger.warning(f"No transaction found with ID {transaction_id} to update status.")
        else:
             logger.info(f"Transaction {transaction_id} status updated to {new_status.name}")
        await self.session.flush() # 변경 사항 반영

    async def update_wallet_balance(self, wallet_id: UUID, new_balance: Decimal) -> None:
        """지갑 잔액 업데이트

        Args:
            wallet_id: 업데이트할 지갑 ID
            new_balance: 새로운 잔액
        """
        stmt = (
            update(Wallet)
            .where(Wallet.id == wallet_id)
            .values(balance=new_balance, updated_at=datetime.now(timezone.utc)) # updated_at 추가 가정
        )
        result = await self.session.execute(stmt)
        if result.rowcount == 0:
             logger.warning(f"No wallet found with ID {wallet_id} to update balance.")
        else:
             logger.info(f"Wallet {wallet_id} balance updated to {new_balance}")
        await self.session.flush()

    # ... 기타 필요한 Wallet 및 Transaction 관련 CRUD 메서드 추가 