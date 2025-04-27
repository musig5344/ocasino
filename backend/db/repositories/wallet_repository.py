"""
지갑 리포지토리
지갑, 트랜잭션, 정산 등 관련 데이터 액세스
"""
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID, uuid4
from decimal import Decimal
from datetime import datetime, date
import json
import decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, text, func, and_
from sqlalchemy.orm import joinedload

from backend.models.domain.wallet import Wallet, Transaction, Balance, TransactionType, TransactionStatus
from backend.partners.models import Partner
from backend.cache.memory_cache import MemoryCache
from backend.cache.redis_cache import get_redis_client

class WalletRepository:
    """향상된 지갑 저장소 - 읽기/쓰기 분리 패턴 적용"""
    
    def __init__(self, read_session: AsyncSession, write_session: AsyncSession = None):
        """
        지갑 저장소 초기화
        
        Args:
            read_session: 읽기 전용 세션
            write_session: 쓰기 전용 세션 (없을 경우 read_session 사용)
        """
        self.read_session = read_session
        self.write_session = write_session or read_session
        self.memory_cache = MemoryCache()  # L1 캐시
        self.redis = None # L2 캐시 - 비동기 초기화 필요
    
    async def initialize(self):
        """비동기 Redis 클라이언트 초기화"""
        if self.redis is None:
             self.redis = await get_redis_client()
        return self
    
    async def get_wallet(self, wallet_id: UUID, for_update: bool = False) -> Optional[Wallet]:
        """지갑 조회 (캐싱 및 읽기/쓰기 분리 적용)"""
        # Redis 클라이언트가 초기화되었는지 확인
        if self.redis is None:
            # 필요 시 여기서 초기화하거나, initialize() 호출을 강제하는 방식 고려
            # raise RuntimeError("Redis client not initialized. Call initialize() first.")
            # 또는 로깅 후 None/DB 조회만 진행
             print("Warning: Redis client not initialized in get_wallet. Call initialize() first.") # 임시 경고

        if for_update:
            # 쓰기 작업용 세션 사용 (락 획득)
            query = select(Wallet).where(Wallet.id == wallet_id).with_for_update()
            result = await self.write_session.execute(query)
            return result.scalars().first()
        else:
            # 캐시 확인
            cache_key = f"wallet:{wallet_id}"
            wallet_dict = self.memory_cache.get(cache_key)
            
            if wallet_dict:
                return self._create_wallet_from_dict(wallet_dict)
            
            # Redis 캐시 확인 (초기화된 경우에만 시도)
            if self.redis:
                try:
                    redis_result = await self.redis.get(cache_key)
                    if redis_result:
                        try:
                            wallet_dict = json.loads(redis_result)
                            # L1 캐시에 저장 (짧은 TTL)
                            self.memory_cache.set(cache_key, wallet_dict, ttl=60)
                            return self._create_wallet_from_dict(wallet_dict)
                        except json.JSONDecodeError:
                            # 캐시 파싱 오류 시 DB 조회로 넘어감
                            pass
                except Exception as e:
                    print(f"Error reading from Redis: {e}")
            
            # DB 조회 (읽기 전용)
            query = select(Wallet).where(Wallet.id == wallet_id)
            result = await self.read_session.execute(query)
            wallet = result.scalars().first()
            
            # 캐시 저장 (Redis 초기화된 경우에만 시도)
            if wallet and self.redis:
                wallet_dict = {
                    "id": str(wallet.id),
                    "player_id": str(wallet.player_id),
                    "partner_id": str(wallet.partner_id),
                    "balance": str(wallet.balance),
                    "currency": wallet.currency,
                    "is_active": wallet.is_active,
                    "is_locked": wallet.is_locked,
                    "created_at": wallet.created_at.isoformat(),
                    "updated_at": wallet.updated_at.isoformat()
                }
                # L1 캐시 (60초)
                self.memory_cache.set(cache_key, wallet_dict, ttl=60)
                # L2 캐시 (5분)
                try:
                    await self.redis.set(cache_key, json.dumps(wallet_dict), ex=300)
                except Exception as e:
                    # Redis 오류 처리 (로깅 등)
                     print(f"Error writing to Redis: {e}")
            
            return wallet
    
    async def get_player_wallet(
        self, player_id: UUID, partner_id: UUID, for_update: bool = False
    ) -> Optional[Wallet]:
        """플레이어 및 파트너 ID로 지갑 조회 (캐싱 및 읽기/쓰기 분리 적용)"""
        # Redis 클라이언트 초기화 확인 (get_wallet과 유사하게)
        if self.redis is None:
             print("Warning: Redis client not initialized in get_player_wallet. Call initialize() first.")

        cache_key = f"wallet:player:{player_id}:partner:{partner_id}"
        
        if for_update:
            # 쓰기 작업용 세션 사용 (락 획득)
            query = select(Wallet).where(
                Wallet.player_id == player_id,
                Wallet.partner_id == partner_id
            ).with_for_update()
            result = await self.write_session.execute(query)
            return result.scalars().first()
        else:
            # 캐싱 로직 (get_wallet과 유사)
            wallet_dict = self.memory_cache.get(cache_key)
            if wallet_dict:
                return self._create_wallet_from_dict(wallet_dict)
            
            if self.redis:
                 try:
                     redis_result = await self.redis.get(cache_key)
                     if redis_result:
                         try:
                             wallet_dict = json.loads(redis_result)
                             self.memory_cache.set(cache_key, wallet_dict, ttl=60)
                             return self._create_wallet_from_dict(wallet_dict)
                         except json.JSONDecodeError:
                              pass # 캐시 파싱 오류 시 DB 조회로 넘어감
                 except Exception as e:
                     print(f"Error reading from Redis: {e}")
            
            # DB 조회 (읽기 전용)
            query = select(Wallet).where(
                Wallet.player_id == player_id,
                Wallet.partner_id == partner_id
            )
            result = await self.read_session.execute(query)
            wallet = result.scalars().first()
            
            # 캐시 저장 (Redis 초기화된 경우)
            if wallet and self.redis:
                wallet_dict = {
                    "id": str(wallet.id),
                    "player_id": str(wallet.player_id),
                    "partner_id": str(wallet.partner_id),
                    "balance": str(wallet.balance),
                    "currency": wallet.currency,
                    "is_active": wallet.is_active,
                    "is_locked": wallet.is_locked,
                    "created_at": wallet.created_at.isoformat(),
                    "updated_at": wallet.updated_at.isoformat()
                }
                # L1 캐시 (60초)
                self.memory_cache.set(cache_key, wallet_dict, ttl=60)
                # L2 캐시 (5분)
                try:
                     await self.redis.set(cache_key, json.dumps(wallet_dict), ex=300)
                except Exception as e:
                     print(f"Error writing to Redis: {e}")
            
            return wallet

    async def get_player_wallet_or_none(self, player_id: UUID, partner_id: UUID) -> Optional[Wallet]:
        """
        플레이어 ID와 파트너 ID로 지갑을 조회하고, 없으면 None을 반환합니다.
        (캐싱 없이 DB 직접 조회)
        """
        try:
            # 이 메서드는 주로 지갑 생성 전 존재 여부 확인에 쓰이므로,
            # 캐싱보다는 항상 최신 DB 상태를 확인하는 것이 안전할 수 있습니다.
            # 또는 get_player_wallet과 동일한 캐싱 로직을 적용할 수도 있습니다.
            # 여기서는 DB 직접 조회를 사용합니다.
            query = select(Wallet).where(
                and_(
                    Wallet.player_id == player_id,
                    Wallet.partner_id == partner_id
                )
            )
            # 읽기 세션을 사용하여 조회
            result = await self.read_session.execute(query)
            wallet = result.scalars().first()
            return wallet
        except Exception as e:
            # 로깅 추가
            # logger.error(f"Error getting wallet or none for player {player_id}, partner {partner_id}: {e}")
            print(f"[ERROR] Error getting wallet or none for player {player_id}, partner {partner_id}: {e}") # 임시 로깅
            return None

    async def create_wallet(self, wallet: Wallet) -> Wallet:
        """새 지갑 생성 (쓰기 세션 사용)"""
        self.write_session.add(wallet)
        await self.write_session.flush()
        # 생성 시에는 캐시 무효화 불필요 (조회 시 캐시됨)
        return wallet
    
    async def update_wallet_balance(
        self, wallet_id: UUID, amount: Decimal, operation: str, 
        player_id: UUID, partner_id: UUID # 캐시 무효화를 위해 추가
    ) -> Optional[Tuple[Wallet, Decimal]]:
        """
        지갑 잔액 업데이트 (쓰기 세션 사용, 캐시 무효화 포함)
        operation: 'add' 또는 'subtract'
        """
        wallet = await self.get_wallet(wallet_id, for_update=True) # 쓰기 세션 사용
        if not wallet:
            return None
        
        original_balance = wallet.balance
        
        if operation == 'add':
            wallet.balance += amount
        elif operation == 'subtract':
            # 실제 차감 로직은 서비스 레벨에서 잔액 체크 후 수행될 것이므로 여기선 단순 연산
            wallet.balance -= amount 
        else:
            raise ValueError(f"Invalid operation: {operation}")
        
        await self.write_session.flush()
        
        # 관련 캐시 무효화
        await self._invalidate_wallet_cache(wallet_id, player_id, partner_id)
        
        return wallet, original_balance
    
    async def get_transaction(self, tx_id: UUID) -> Optional[Transaction]:
        """ID로 트랜잭션 조회 (읽기 세션 사용)"""
        result = await self.read_session.execute(
            select(Transaction).where(Transaction.id == tx_id)
        )
        return result.scalars().first()
    
    async def get_transaction_by_reference(
        self, 
        reference_id: str, 
        player_id: UUID,
        session: Optional[AsyncSession] = None
    ) -> Optional[Transaction]:
        """Reference ID와 Player ID로 트랜잭션 조회 (지정된 세션 또는 읽기 세션 사용)"""
        use_session = session or self.read_session
        
        query = select(Transaction).where(
            Transaction.reference_id == reference_id,
            Transaction.player_id == player_id 
        )
            
        result = await use_session.execute(query)
        return result.scalars().first()
    
    async def create_transaction(self, transaction: Transaction) -> Transaction:
        """새 트랜잭션 생성 (쓰기 세션 사용, 캐시 무효화 포함)"""
        self.write_session.add(transaction)
        await self.write_session.flush()
        
        # 관련 캐시 무효화 (지갑 잔액이 변경되었으므로)
        await self._invalidate_wallet_cache(transaction.wallet_id, 
                                          transaction.player_id, 
                                          transaction.partner_id)
        
        return transaction
    
    async def get_player_transactions(
        self, 
        player_id: UUID, 
        partner_id: UUID, 
        tx_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        skip: int = 0, # offset -> skip
        limit: int = 100
    ) -> Tuple[List[Transaction], int]: # 총 개수도 반환하도록 수정
        """플레이어 트랜잭션 내역 조회 (읽기 세션 사용, 인덱스 활용)"""
        # 복합 인덱스를 활용하는 쿼리
        query = select(Transaction).where(
            Transaction.player_id == player_id,
            Transaction.partner_id == partner_id
        )
        
        if tx_type:
            query = query.where(Transaction.transaction_type == tx_type)
        if start_date:
            # 파티셔닝 고려 시, created_at 범위 조건은 필수
            query = query.where(Transaction.created_at >= start_date) 
        if end_date:
            query = query.where(Transaction.created_at <= end_date)
        
        # 전체 개수 쿼리 (조건 적용 후)
        count_query = select(func.count()).select_from(query.subquery())
        total_count_result = await self.read_session.execute(count_query)
        total = total_count_result.scalar_one_or_none() or 0
        
        # 페이징 및 정렬 적용
        query = query.order_by(Transaction.created_at.desc())
        query = query.offset(skip).limit(limit)
        
        # 결과 조회
        result = await self.read_session.execute(query)
        transactions = result.scalars().all()
        
        return transactions, total

    async def get_balances(self, partner_id: UUID) -> List[Balance]:
        """파트너별 통화별 잔액 현황 조회 (읽기 세션 사용)"""
        # 잔액 정보는 자주 변경될 수 있고, 집계 정보이므로 캐싱 효과가 적을 수 있음
        result = await self.read_session.execute(
            select(Balance).where(Balance.partner_id == partner_id)
        )
        return result.scalars().all()
    
    async def update_balance(self, balance: Balance) -> Balance:
        """잔액 현황 업데이트 (쓰기 세션 사용)"""
        # 이 작업은 보통 내부 정산 로직에서 호출되므로 직접 캐시 무효화는 생략
        self.write_session.add(balance)
        await self.write_session.flush()
        return balance
    
    async def get_daily_summary(
        self, partner_id: UUID, date_value: date, currency: str
    ) -> Dict[str, Decimal]:
        """일별 트랜잭션 요약 조회 (읽기 세션 사용, 캐싱 적용)"""
        # 캐시 키
        cache_key = f"summary:daily:{partner_id}:{date_value}:{currency}"
        
        # 캐시 확인 (L2 Redis만 사용)
        redis_result = await self.redis.get(cache_key)
        if redis_result:
            try:
                summary_dict = json.loads(redis_result)
                # Decimal로 변환
                return {k: Decimal(v) for k, v in summary_dict.items()}
            except (json.JSONDecodeError, decimal.InvalidOperation):
                # 캐시 오류 시 무시하고 DB 조회로 넘어감
                pass
        
        # 최적화된 쿼리 사용 (파티셔닝 및 인덱스 활용)
        start_datetime = datetime.combine(date_value, datetime.min.time())
        end_datetime = datetime.combine(date_value, datetime.max.time())
        
        # Raw SQL 사용 (SQLAlchemy Core Expression으로도 가능)
        query = text("""
            SELECT 
                COALESCE(SUM(CASE WHEN transaction_type = :deposit THEN amount ELSE 0 END), 0) as deposit_total,
                COALESCE(SUM(CASE WHEN transaction_type = :withdrawal THEN amount ELSE 0 END), 0) as withdrawal_total,
                COALESCE(SUM(CASE WHEN transaction_type = :bet THEN amount ELSE 0 END), 0) as bet_total,
                COALESCE(SUM(CASE WHEN transaction_type = :win THEN amount ELSE 0 END), 0) as win_total,
                COALESCE(SUM(CASE WHEN transaction_type = :commission THEN amount ELSE 0 END), 0) as commission_total
            FROM transactions
            WHERE partner_id = :partner_id 
                AND created_at BETWEEN :start_datetime AND :end_datetime
                AND currency = :currency
                AND status = :completed_status -- COMPLETED 상태만 집계
        """)
        
        params = {
            "partner_id": partner_id, 
            "start_datetime": start_datetime, 
            "end_datetime": end_datetime, 
            "currency": currency,
            "deposit": TransactionType.DEPOSIT.value, # Enum 값 사용
            "withdrawal": TransactionType.WITHDRAWAL.value,
            "bet": TransactionType.BET.value,
            "win": TransactionType.WIN.value,
            "commission": TransactionType.COMMISSION.value,
            "completed_status": TransactionStatus.COMPLETED.value
        }
        
        result = await self.read_session.execute(query, params)
        row = result.fetchone()
        
        # 결과 처리
        summary = {
            "deposit_total": Decimal(row.deposit_total if row else 0),
            "withdrawal_total": Decimal(row.withdrawal_total if row else 0),
            "bet_total": Decimal(row.bet_total if row else 0),
            "win_total": Decimal(row.win_total if row else 0),
            "commission_total": Decimal(row.commission_total if row else 0)
        }
        
        # 캐시 저장 (1일 TTL)
        summary_dict = {k: str(v) for k, v in summary.items()}
        await self.redis.set(cache_key, json.dumps(summary_dict), ex=86400) # 24 * 60 * 60
        
        return summary

    # --- Helper Methods ---
    
    async def _invalidate_wallet_cache(
        self, wallet_id: UUID, player_id: UUID, partner_id: UUID
    ) -> None:
        """지갑 관련 캐시 무효화"""
        if self.redis is None:
            print("Warning: Redis client not initialized in _invalidate_wallet_cache.")
            return # Redis 없으면 캐시 무효화 불가능

        wallet_key = f"wallet:{wallet_id}"
        player_wallet_key = f"wallet:player:{player_id}:partner:{partner_id}"
        
        # L1 캐시 무효화
        self.memory_cache.delete(wallet_key)
        self.memory_cache.delete(player_wallet_key)
        
        # L2 캐시 무효화
        try:
            await self.redis.delete(wallet_key)
            await self.redis.delete(player_wallet_key)
        except Exception as e:
            # 로깅 또는 오류 처리
            print(f"Error invalidating Redis cache: {e}")
    
    def _create_wallet_from_dict(self, wallet_dict: Dict[str, Any]) -> Wallet:
        """딕셔너리에서 지갑 객체 생성 (오류 처리 강화)"""
        try:
            return Wallet(
                id=UUID(wallet_dict["id"]),
                player_id=UUID(wallet_dict["player_id"]),
                partner_id=UUID(wallet_dict["partner_id"]),
                balance=Decimal(wallet_dict["balance"]),
                currency=wallet_dict["currency"],
                is_active=wallet_dict["is_active"],
                is_locked=wallet_dict["is_locked"],
                # ISO 포맷 문자열을 datetime 객체로 변환
                created_at=datetime.fromisoformat(wallet_dict["created_at"].replace('Z', '+00:00')) if isinstance(wallet_dict.get("created_at"), str) else wallet_dict.get("created_at"),
                updated_at=datetime.fromisoformat(wallet_dict["updated_at"].replace('Z', '+00:00')) if isinstance(wallet_dict.get("updated_at"), str) else wallet_dict.get("updated_at")
            )
        except (KeyError, ValueError, TypeError, decimal.InvalidOperation) as e:
            # 캐시 데이터 파싱 오류 로깅 또는 처리
            print(f"Error creating Wallet from cache dict: {e}, dict: {wallet_dict}") 
            # 오류 발생 시 None 반환 또는 예외 발생 선택
            return None 