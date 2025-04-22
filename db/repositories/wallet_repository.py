"""
지갑 리포지토리
지갑, 트랜잭션, 정산 등 관련 데이터 액세스
"""
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
from decimal import Decimal
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, text, func
from sqlalchemy.orm import joinedload

from backend.models.domain.wallet import Wallet, Transaction, Balance
from backend.models.domain.partner import Partner

class WalletRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_wallet(self, wallet_id: UUID, for_update: bool = False) -> Optional[Wallet]:
        """ID로 지갑 조회"""
        query = select(Wallet).where(Wallet.id == wallet_id)
        if for_update:
            query = query.with_for_update()
        
        result = await self.session.execute(query)
        return result.scalars().first()
    
    async def get_player_wallet(
        self, player_id: UUID, partner_id: UUID, for_update: bool = False
    ) -> Optional[Wallet]:
        """플레이어 및 파트너 ID로 지갑 조회"""
        query = select(Wallet).where(
            Wallet.player_id == player_id,
            Wallet.partner_id == partner_id
        )
        if for_update:
            query = query.with_for_update()
        
        result = await self.session.execute(query)
        return result.scalars().first()
    
    async def create_wallet(self, wallet: Wallet) -> Wallet:
        """새 지갑 생성"""
        self.session.add(wallet)
        await self.session.flush()
        return wallet
    
    async def update_wallet_balance(
        self, wallet_id: UUID, amount: Decimal, operation: str
    ) -> Optional[Tuple[Wallet, Decimal]]:
        """
        지갑 잔액 업데이트 
        operation: 'add' 또는 'subtract'
        """
        wallet = await self.get_wallet(wallet_id, for_update=True)
        if not wallet:
            return None
        
        original_balance = wallet.balance
        
        if operation == 'add':
            wallet.balance += amount
        elif operation == 'subtract':
            wallet.balance -= amount
        else:
            raise ValueError(f"Invalid operation: {operation}")
        
        await self.session.flush()
        return wallet, original_balance
    
    async def get_transaction(self, tx_id: UUID) -> Optional[Transaction]:
        """ID로 트랜잭션 조회"""
        result = await self.session.execute(
            select(Transaction).where(Transaction.id == tx_id)
        )
        return result.scalars().first()
    
    async def get_transaction_by_reference(self, reference_id: str) -> Optional[Transaction]:
        """Reference ID로 트랜잭션 조회 (멱등성 지원)"""
        result = await self.session.execute(
            select(Transaction).where(Transaction.reference_id == reference_id)
        )
        return result.scalars().first()
    
    async def create_transaction(self, transaction: Transaction) -> Transaction:
        """새 트랜잭션 생성"""
        self.session.add(transaction)
        await self.session.flush()
        return transaction
    
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
        """플레이어 트랜잭션 내역 조회"""
        query = select(Transaction).where(
            Transaction.player_id == player_id,
            Transaction.partner_id == partner_id
        )
        
        if tx_type:
            query = query.where(Transaction.transaction_type == tx_type)
        if start_date:
            query = query.where(Transaction.created_at >= start_date)
        if end_date:
            query = query.where(Transaction.created_at <= end_date)
        
        query = query.order_by(Transaction.created_at.desc()).offset(offset).limit(limit)
        
        result = await self.session.execute(query)
        return result.scalars().all()
    
    async def get_balances(self, partner_id: UUID) -> List[Balance]:
        """파트너별 통화별 잔액 현황 조회"""
        result = await self.session.execute(
            select(Balance).where(Balance.partner_id == partner_id)
        )
        return result.scalars().all()
    
    async def update_balance(self, balance: Balance) -> Balance:
        """잔액 현황 업데이트"""
        self.session.add(balance)
        await self.session.flush()
        return balance
    
    async def get_daily_summary(
        self, partner_id: UUID, date_value: date, currency: str
    ) -> Dict[str, Decimal]:
        """일별 트랜잭션 요약 조회"""
        query = text("""
            SELECT 
                SUM(CASE WHEN transaction_type = 'deposit' THEN amount ELSE 0 END) as deposit_total,
                SUM(CASE WHEN transaction_type = 'withdrawal' THEN amount ELSE 0 END) as withdrawal_total,
                SUM(CASE WHEN transaction_type = 'bet' THEN amount ELSE 0 END) as bet_total,
                SUM(CASE WHEN transaction_type = 'win' THEN amount ELSE 0 END) as win_total,
                SUM(CASE WHEN transaction_type = 'commission' THEN amount ELSE 0 END) as commission_total
            FROM transactions
            WHERE partner_id = :partner_id 
                AND DATE(created_at) = :date_value
                AND currency = :currency
        """)
        
        result = await self.session.execute(
            query, 
            {"partner_id": partner_id, "date_value": date_value, "currency": currency}
        )
        row = result.fetchone()
        
        if not row:
            return {
                "deposit_total": Decimal("0.0"),
                "withdrawal_total": Decimal("0.0"),
                "bet_total": Decimal("0.0"),
                "win_total": Decimal("0.0"),
                "commission_total": Decimal("0.0")
            }
        
        return {
            "deposit_total": row.deposit_total or Decimal("0.0"),
            "withdrawal_total": row.withdrawal_total or Decimal("0.0"),
            "bet_total": row.bet_total or Decimal("0.0"),
            "win_total": row.win_total or Decimal("0.0"),
            "commission_total": row.commission_total or Decimal("0.0")
        }