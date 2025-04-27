"""
지갑 서비스
트랜잭션 처리, 잔액 관리 등 비즈니스 로직 담당
"""
import logging
from uuid import UUID, uuid4
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any, List, Tuple, Callable, Type
from datetime import datetime, timezone, timedelta
import uuid
import json

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, NoResultFound
from redis.asyncio import Redis

from backend.models.domain.wallet import Wallet, Transaction, TransactionType, TransactionStatus
from backend.partners.models import Partner
from backend.repositories.wallet_repository import WalletRepository
from backend.repositories.game_repository import GameRepository
from backend.partners.repository import PartnerRepository
from backend.schemas.wallet import (
    WalletCreate, DebitRequest, CreditRequest, 
    RollbackRequest, BalanceResponse, TransactionResponse
)
from backend.domain_events import publish_event, DomainEventType
from backend.core.exceptions import (
    InsufficientFundsError, DuplicateTransactionError, 
    WalletNotFoundError, CurrencyMismatchError,
    TransactionNotFoundError, ValidationError,
    PartnerNotFoundError, WalletOperationError
)
from backend.domain_events.events import TransactionCompletedEvent, WalletBalanceChangedEvent
from backend.utils.encryption import encrypt_aes_gcm, decrypt_aes_gcm

logger = logging.getLogger(__name__)

# 타입 힌트용 세션 팩토리 타입 정의
AsyncSessionFactory = Callable[[], AsyncSession]

class WalletService:
    """향상된 지갑 서비스 - WalletRepository 주입"""
    
    def __init__(
        self,
        wallet_repo: WalletRepository, # wallet_repo 주입받도록 변경
        redis_client: Optional[Redis] = None
    ):
        """
        지갑 서비스 초기화 (WalletRepository 및 Redis 클라이언트 주입)

        Args:
            wallet_repo: WalletRepository 인스턴스
            redis_client: Redis 캐시 클라이언트 (선택적)
        """
        # 세션 팩토리 제거
        # self.read_db_factory = read_db_factory
        # self.write_db_factory = write_db_factory or read_db_factory
        self.wallet_repo = wallet_repo # 주입받은 리포지토리 저장
        self.redis = redis_client

        # 리포지토리는 이제 주입받으므로 여기서 초기화하지 않음
        # self.wallet_repo = WalletRepository() # 더 이상 세션 바인딩 안 함
        # self.partner_repo = PartnerRepository() # 더 이상 세션 바인딩 안 함

        # TODO: RedisCache 의존성 처리 방식 결정 필요 (여기서는 임시로 None 처리)
        # self.redis = redis_client # 주입받은 Redis 클라이언트 사용

    async def initialize(self):
        """비동기 초기화 (필요 시)"""
        # Redis 초기화 등 필요한 작업 수행
        # if self.redis:
        #     await self.redis.initialize()
        # logger.info("WalletService initialized (using session factories).") # 로그 메시지 수정
        logger.info("WalletService initialized (with injected WalletRepository).")
        return self

    # --- 캐시 데코레이터는 Redis 클라이언트가 확정된 후 다시 적용 ---
    # @cache_result(key_prefix="wallet", ttl=300)
    # ------------------------------------------------------------
    async def get_wallet(
        self, player_id: UUID, partner_id: UUID, use_cache: bool = True
    ) -> Optional[Wallet]:
        """플레이어 지갑 조회 (캐싱 적용 보류). 찾지 못하면 WalletNotFoundError 발생"""
        # TODO: 캐싱 로직 복구 필요 (self.redis 사용)

        # 세션 팩토리 사용 제거, 주입된 repo 사용
        # async with self.read_db_factory() as session:
        #     wallet_repo = WalletRepository(session) # 메서드 내 리포지토리 생성 제거
        try:
            # for_update=False 기본값 사용
            # 주입된 self.wallet_repo 사용
            wallet = await self.wallet_repo.get_player_wallet(player_id, partner_id)
            if not wallet:
                 logger.warning(f"Wallet not found for player {player_id}, partner {partner_id} in get_wallet")
                 raise WalletNotFoundError(f"Wallet not found for player {player_id}, partner {partner_id}")

            # TODO: 캐싱 로직 복구 필요 (DB 조회 후 캐시에 저장)

            return wallet
        except NoResultFound: # get_player_wallet이 NoResultFound 발생시킬 경우
             logger.warning(f"Wallet not found for player {player_id}, partner {partner_id} (NoResultFound)")
             raise WalletNotFoundError(f"Wallet not found for player {player_id}, partner {partner_id}")


    async def create_wallet(self, player_id: UUID, partner_id: UUID, currency: str) -> Wallet:
        """ 지갑 생성 (내부 사용) - 이 메서드는 ensure_wallet_exists 내에서 호출됨 """
        # 세션 팩토리 사용 제거, 주입된 repo 사용
        # async with self.write_db_factory() as session:
            # wallet_repo = WalletRepository(session) # <<< 여기서 repo 생성 제거
            
            # 디버깅 코드 제거
            # print(f"--- DEBUG: WalletService.create_wallet (inside async with) ---")
            # print(f"DEBUG: Type of wallet_repo created: {type(wallet_repo)}")
            # print(f"DEBUG: Has 'get_player_wallet_or_none'? {'get_player_wallet_or_none' in dir(wallet_repo)}")
            # print(f"--- END DEBUG ---")

        try:
            # 지갑 생성 전에 이미 존재하는지 확인 (이중 생성 방지)
            # 주입된 self.wallet_repo 사용
            existing_wallet = await self.wallet_repo.get_player_wallet_or_none(player_id, partner_id)
            if existing_wallet:
                logger.warning(f"Wallet already exists for player {player_id}, partner {partner_id} (in create_wallet). Returning existing.")
                return existing_wallet

            # 파트너 존재 여부 확인 (필요 시, 리포지토리 직접 사용 또는 별도 서비스 주입)
            # partner = await PartnerRepository(self.write_db_factory()).get_partner_by_id(partner_id)
            # -> PartnerRepository도 주입받거나, PartnerService를 사용하는 방식으로 변경 필요

            wallet = Wallet(
                player_id=player_id,
                partner_id=partner_id,
                balance=Decimal("0"),
                currency=currency,
                is_active=True,
                is_locked=False
            )
            # 주입된 self.wallet_repo 사용
            created_wallet = await self.wallet_repo.create_wallet(wallet)
            logger.info(f"Created new wallet {created_wallet.id} for player {player_id}, partner {partner_id}")
            return created_wallet
        except AttributeError as e:
             # 디버깅 print 구문 제거
             # print(f"DEBUG: AttributeError caught unexpectedly in create_wallet: {e}")
             logger.error(f"Unexpected AttributeError in create_wallet for {player_id}: {e}")
             raise WalletOperationError(f"Failed to create wallet due to unexpected attribute error: {e}") from e
        except Exception as e:
            logger.exception(f"Error creating wallet for player {player_id}, partner {partner_id}: {e}")
            raise WalletOperationError(f"Failed to create wallet: {e}") from e

    async def ensure_wallet_exists(
        self, player_id: UUID, partner_id: UUID, currency: str
    ) -> Tuple[Wallet, bool]:
        """ 지갑 존재 확인 및 필요 시 생성 """
        try:
            # get_wallet 호출 (캐시 시도 포함)
            wallet = await self.get_wallet(player_id, partner_id, use_cache=True)
            created = False
        except WalletNotFoundError:
            # create_wallet 호출 (내부적으로 쓰기 세션 사용)
            wallet = await self.create_wallet(player_id, partner_id, currency)
            created = True

        if wallet.currency != currency:
            raise CurrencyMismatchError(
                expected_currency=currency,
                actual_currency=wallet.currency
            )

        return wallet, created

    async def get_balance(
        self, player_id: UUID, partner_id: UUID # reference_id 제거
    ) -> BalanceResponse:
        """ 플레이어 잔액 조회 """
        # get_wallet 호출 (캐시 시도 포함)
        wallet = await self.get_wallet(player_id, partner_id, use_cache=True)

        # 지갑 상태 확인 (get_wallet에서 NotFound는 처리됨)
        if not wallet.is_active:
             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Wallet is not active")

        return BalanceResponse(
            player_id=player_id,
            partner_id=partner_id,
            balance=wallet.balance,
            currency=wallet.currency,
            timestamp=datetime.now(timezone.utc) # 현재 시간 사용
        )

    async def debit(self, request: DebitRequest, partner_id: UUID) -> TransactionResponse:
        """ 지갑에서 금액 차감 (베팅 등) """
        player_id = request.player_id
        logger.info(f"Debit request received: {request.reference_id} for player {player_id}")

        # 세션 팩토리 사용 제거, 주입된 repo 사용
        # async with self.write_db_factory() as session:
            # wallet_repo = WalletRepository(session) # 세션 기반 리포지토리 생성 제거
        # 멱등성 체크 (partner_id 사용)
        # 주입된 self.wallet_repo 사용
        existing_tx = await self.wallet_repo.get_transaction_by_reference(request.reference_id, partner_id)
        if existing_tx:
            logger.warning(f"Duplicate debit transaction detected: {request.reference_id}")
            return await self._create_transaction_response(existing_tx)

        created_tx: Optional[Transaction] = None
        updated_balance: Optional[Decimal] = None
        wallet_id: Optional[UUID] = None
        player_id_for_cache: Optional[UUID] = None
        partner_id_for_cache: Optional[UUID] = None

        try:
            # 지갑 조회 (잠금 필요 시 for_update=True)
            # 주입된 self.wallet_repo 사용
            # TODO: Repository가 세션을 관리해야 함. 여기서는 get_player_wallet이 세션 컨텍스트 내에서 실행된다고 가정.
            wallet = await self.wallet_repo.get_player_wallet(player_id, partner_id, for_update=True)
            if not wallet:
                raise WalletNotFoundError(f"Wallet not found for player {player_id}")

            wallet_id = wallet.id
            player_id_for_cache = wallet.player_id
            partner_id_for_cache = wallet.partner_id

            # 통화 및 잔액 확인
            if wallet.currency != request.currency:
                raise CurrencyMismatchError(expected_currency=wallet.currency, actual_currency=request.currency)
            if not wallet.is_active:
                 raise WalletOperationError(f"Wallet for player {player_id} is not active.")
            if wallet.is_locked:
                 raise WalletOperationError(f"Wallet for player {player_id} is locked.")
            if wallet.balance < request.amount:
                raise InsufficientFundsError(
                     player_id=player_id,
                     requested_amount=request.amount,
                     current_balance=wallet.balance
                )

            # 트랜잭션 생성 준비
            original_balance = wallet.balance
            updated_balance = original_balance - request.amount
            try:
                encrypted_amount = encrypt_aes_gcm(str(request.amount))
            except Exception as e:
                logger.error(f"Encryption failed during debit for {request.reference_id}: {e}")
                raise WalletOperationError("Failed to encrypt transaction amount.") from e

            transaction = Transaction(
                id=uuid4(),
                reference_id=request.reference_id,
                wallet_id=wallet.id,
                player_id=player_id,
                partner_id=partner_id,
                transaction_type=request.transaction_type or TransactionType.BET, # 요청 타입 사용, 기본 BET
                _encrypted_amount=encrypted_amount,
                amount=request.amount,
                currency=request.currency,
                status=TransactionStatus.COMPLETED,
                original_balance=original_balance,
                updated_balance=updated_balance,
                game_id=request.game_id,
                # round_id=request.round_id # 모델에 round_id 없음
            )

            # 지갑 잔액 업데이트 및 트랜잭션 저장
            # 주입된 self.wallet_repo 사용
            await self.wallet_repo.update_wallet_balance(wallet.id, updated_balance)
            logger.info(f"Wallet {wallet.id} balance updated to {updated_balance} for debit tx {request.reference_id}")

            # 주입된 self.wallet_repo 사용
            created_tx = await self.wallet_repo.create_transaction(transaction)
            if not created_tx.created_at:
                 created_tx.created_at = datetime.now(timezone.utc)
            logger.info(f"Debit transaction {created_tx.id} created successfully.")

            # >>> COMMIT은 이제 Repository 내부에서 처리되어야 함 <<<
            # await session.commit()
            # logger.info(f"Debit transaction {created_tx.id} committed successfully.")

        except IntegrityError as e:
            logger.error(f"Integrity error during debit {request.reference_id}: {e}")
            # 멱등성 재확인 (partner_id 사용)
            # 주입된 self.wallet_repo 사용
            existing_tx_after_error = await self.wallet_repo.get_transaction_by_reference(request.reference_id, partner_id)
            if existing_tx_after_error:
                logger.warning(f"Duplicate debit transaction confirmed after integrity error: {request.reference_id}")
                return await self._create_transaction_response(existing_tx_after_error)
            raise DuplicateTransactionError(f"Potential duplicate transaction after rollback: {request.reference_id}") from e
        except (WalletNotFoundError, CurrencyMismatchError, InsufficientFundsError, WalletOperationError) as e:
             logger.error(f"Business logic error during debit {request.reference_id}: {e}")
             raise # Re-raise specific business errors
        except Exception as e:
            logger.exception(f"Unexpected error during debit {request.reference_id}: {e}")
            raise WalletOperationError(f"Failed to process debit: {request.reference_id}") from e

        # 트랜잭션 성공 후 처리
        if created_tx and updated_balance is not None and player_id_for_cache and partner_id_for_cache:
            # 캐시 무효화
            await self.invalidate_wallet_cache(player_id_for_cache, partner_id_for_cache)
            # 이벤트 발행 (업데이트된 잔액 사용)
            await self._publish_transaction_event(created_tx, updated_balance)
            return await self._create_transaction_response(created_tx)
        else:
            # 이 경우는 정상적인 흐름에서 발생하기 어려움 (오류 처리됨)
            logger.error(f"Debit completed for {request.reference_id} but failed to get necessary data for response/event.")
            raise WalletOperationError(f"Failed to finalize debit operation: {request.reference_id}")


    async def credit(self, request: CreditRequest, partner_id: UUID) -> TransactionResponse:
        """ 지갑에 금액 추가 (승리 등) """
        player_id = request.player_id
        logger.info(f"Credit request received: {request.reference_id} for player {player_id}")

        # 세션 팩토리 사용 제거, 주입된 repo 사용
        # async with self.write_db_factory() as session:
            # wallet_repo = WalletRepository(session)
        # 멱등성 체크 (partner_id 사용)
        # 주입된 self.wallet_repo 사용
        existing_tx = await self.wallet_repo.get_transaction_by_reference(request.reference_id, partner_id)
        if existing_tx:
            logger.warning(f"Duplicate credit transaction detected: {request.reference_id}")
            return await self._create_transaction_response(existing_tx)

        created_tx: Optional[Transaction] = None
        updated_balance: Optional[Decimal] = None
        wallet_id: Optional[UUID] = None
        player_id_for_cache: Optional[UUID] = None
        partner_id_for_cache: Optional[UUID] = None

        try:
            # ensure_wallet_exists는 내부적으로 get_wallet, create_wallet을 호출하며
            # 이 메소드들은 이미 주입된 self.wallet_repo를 사용하도록 수정되었음
            wallet, created = await self.ensure_wallet_exists(player_id, partner_id, request.currency)
            if created:
                logger.info(f"New wallet created for player {player_id} during credit operation.")

            wallet_id = wallet.id
            player_id_for_cache = wallet.player_id
            partner_id_for_cache = wallet.partner_id

            if not wallet.is_active:
                raise WalletOperationError(f"Wallet for player {player_id} is not active.")
            if wallet.is_locked:
                raise WalletOperationError(f"Wallet for player {player_id} is locked.")

            # 트랜잭션 생성 준비
            original_balance = wallet.balance
            updated_balance = original_balance + request.amount
            try:
                encrypted_amount = encrypt_aes_gcm(str(request.amount))
            except Exception as e:
                logger.error(f"Encryption failed during credit for {request.reference_id}: {e}")
                raise WalletOperationError("Failed to encrypt transaction amount.") from e

            transaction = Transaction(
                id=uuid4(),
                reference_id=request.reference_id,
                wallet_id=wallet.id,
                player_id=player_id,
                partner_id=partner_id,
                transaction_type=request.transaction_type or TransactionType.WIN, # 요청 타입 사용, 기본 WIN
                _encrypted_amount=encrypted_amount,
                amount=request.amount,
                currency=request.currency,
                status=TransactionStatus.COMPLETED,
                original_balance=original_balance,
                updated_balance=updated_balance,
                game_id=request.game_id,
                # round_id=request.round_id
            )

            # 지갑 잔액 업데이트 및 트랜잭션 저장
            # 주입된 self.wallet_repo 사용
            await self.wallet_repo.update_wallet_balance(wallet.id, updated_balance)
            logger.info(f"Wallet {wallet.id} balance updated to {updated_balance} for credit tx {request.reference_id}")

            # 주입된 self.wallet_repo 사용
            created_tx = await self.wallet_repo.create_transaction(transaction)
            if not created_tx.created_at:
                created_tx.created_at = datetime.now(timezone.utc)
            logger.info(f"Credit transaction {created_tx.id} created successfully.")

            # >>> COMMIT은 이제 Repository 내부에서 처리되어야 함 <<<
            # await session.commit()
            # logger.info(f"Credit transaction {created_tx.id} committed successfully.")

        except IntegrityError as e:
            logger.error(f"Integrity error during credit {request.reference_id}: {e}")
            # 멱등성 재확인
            # 주입된 self.wallet_repo 사용
            existing_tx_after_error = await self.wallet_repo.get_transaction_by_reference(request.reference_id, partner_id)
            if existing_tx_after_error:
                logger.warning(f"Duplicate credit transaction confirmed after integrity error: {request.reference_id}")
                return await self._create_transaction_response(existing_tx_after_error)
            raise DuplicateTransactionError(f"Potential duplicate transaction after rollback: {request.reference_id}") from e
        except (WalletNotFoundError, CurrencyMismatchError, WalletOperationError) as e:
            logger.error(f"Business logic error during credit {request.reference_id}: {e}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error during credit {request.reference_id}: {e}")
            raise WalletOperationError(f"Failed to process credit: {request.reference_id}") from e

        # 트랜잭션 성공 후 처리
        if created_tx and updated_balance is not None and player_id_for_cache and partner_id_for_cache:
            # 캐시 무효화
            await self.invalidate_wallet_cache(player_id_for_cache, partner_id_for_cache)
            # 이벤트 발행
            await self._publish_transaction_event(created_tx, updated_balance)
            return await self._create_transaction_response(created_tx)
        else:
            logger.error(f"Credit completed for {request.reference_id} but failed to get necessary data for response/event.")
            raise WalletOperationError(f"Failed to finalize credit operation: {request.reference_id}")


    async def rollback(self, request: RollbackRequest, partner_id: UUID) -> TransactionResponse:
        """ 특정 트랜잭션 롤백 """
        logger.info(f"Rollback request received for transaction: {request.original_reference_id}")
        rollback_reference_id = request.reference_id or f"rollback-{request.original_reference_id}-{uuid4()}"

        # 세션 팩토리 사용 제거, 주입된 repo 사용
        # async with self.write_db_factory() as session:
            # wallet_repo = WalletRepository(session)

        # 롤백 대상 트랜잭션 찾기 (partner_id로 범위 제한)
        # 주입된 self.wallet_repo 사용
        original_tx = await self.wallet_repo.get_transaction_by_reference(request.original_reference_id, partner_id)
        if not original_tx:
            raise TransactionNotFoundError(f"Original transaction {request.original_reference_id} not found for partner {partner_id}")

        # 이미 롤백되었는지 확인
        # 주입된 self.wallet_repo 사용
        existing_rollback = await self.wallet_repo.get_rollback_transaction(original_tx.id)
        if existing_rollback:
            logger.warning(f"Transaction {request.original_reference_id} already rolled back by {existing_rollback.reference_id}")
            return await self._create_transaction_response(existing_rollback)

        # 멱등성 체크: 롤백 트랜잭션 자체의 중복 생성 방지
        # 주입된 self.wallet_repo 사용
        existing_rollback_by_ref = await self.wallet_repo.get_transaction_by_reference(rollback_reference_id, partner_id)
        if existing_rollback_by_ref:
            logger.warning(f"Duplicate rollback transaction detected: {rollback_reference_id}")
            return await self._create_transaction_response(existing_rollback_by_ref)

        # 롤백 가능한 상태인지 확인 (COMPLETED 상태만 롤백 가능)
        if original_tx.status != TransactionStatus.COMPLETED:
            raise WalletOperationError(f"Cannot rollback transaction {request.original_reference_id} with status {original_tx.status}")

        created_tx: Optional[Transaction] = None
        updated_balance: Optional[Decimal] = None
        wallet_id: Optional[UUID] = None
        player_id_for_cache: Optional[UUID] = None
        partner_id_for_cache: Optional[UUID] = None

        try:
            # 대상 지갑 조회 (잠금 필요)
            # 주입된 self.wallet_repo 사용
            wallet = await self.wallet_repo.get_wallet_by_id(original_tx.wallet_id, for_update=True)
            if not wallet:
                # 이 경우는 데이터 불일치 상황일 수 있음
                raise WalletNotFoundError(f"Wallet {original_tx.wallet_id} not found for original transaction {original_tx.id}")

            wallet_id = wallet.id
            player_id_for_cache = wallet.player_id
            partner_id_for_cache = wallet.partner_id

            if not wallet.is_active:
                raise WalletOperationError(f"Wallet {wallet.id} is not active.")
            if wallet.is_locked:
                raise WalletOperationError(f"Wallet {wallet.id} is locked.")

            # 롤백 로직: 원래 트랜잭션 유형에 따라 잔액 복구
            original_amount = original_tx.amount # amount 프로퍼티 사용
            if original_amount is None:
                 raise WalletOperationError(f"Could not decrypt amount for original transaction {original_tx.id}")

            original_balance = wallet.balance
            if original_tx.transaction_type in [TransactionType.BET, TransactionType.WITHDRAWAL]:
                # 베팅/출금 롤백 시 잔액 증가
                updated_balance = original_balance + original_amount
            elif original_tx.transaction_type in [TransactionType.WIN, TransactionType.DEPOSIT]:
                # 승리/입금 롤백 시 잔액 감소
                updated_balance = original_balance - original_amount
            else:
                # 롤백 불가능한 트랜잭션 유형
                raise WalletOperationError(f"Cannot rollback transaction type {original_tx.transaction_type}")

            # 롤백으로 인해 잔액이 음수가 되지 않는지 확인 (선택적이지만 중요할 수 있음)
            if updated_balance < Decimal('0'):
                logger.warning(f"Rollback for tx {original_tx.id} would result in negative balance. Proceeding, but review required.")
                # 정책에 따라 여기서 에러 발생시킬 수도 있음
                # raise WalletOperationError(f"Rollback for tx {original_tx.id} would result in negative balance.")

            try:
                # 롤백 트랜잭션의 amount는 원래 트랜잭션 금액과 동일하게 저장
                encrypted_amount = encrypt_aes_gcm(str(original_amount))
            except Exception as e:
                logger.error(f"Encryption failed during rollback for {rollback_reference_id}: {e}")
                raise WalletOperationError("Failed to encrypt rollback transaction amount.") from e

            rollback_tx = Transaction(
                id=uuid4(),
                reference_id=rollback_reference_id, # 롤백 고유 참조 ID
                wallet_id=wallet.id,
                player_id=wallet.player_id,
                partner_id=partner_id,
                transaction_type=TransactionType.ROLLBACK,
                _encrypted_amount=encrypted_amount, # 원래 금액
                currency=wallet.currency,
                status=TransactionStatus.COMPLETED,
                original_balance=original_balance,
                updated_balance=updated_balance,
                original_transaction_id=original_tx.id # 원본 트랜잭션 ID 연결
            )

            # 지갑 잔액 업데이트 및 롤백 트랜잭션 저장
            # 주입된 self.wallet_repo 사용
            await self.wallet_repo.update_wallet_balance(wallet.id, updated_balance)
            logger.info(f"Wallet {wallet.id} balance updated to {updated_balance} for rollback tx {rollback_reference_id}")

            # 주입된 self.wallet_repo 사용
            created_tx = await self.wallet_repo.create_transaction(rollback_tx)
            if not created_tx.created_at:
                created_tx.created_at = datetime.now(timezone.utc)
            logger.info(f"Rollback transaction {created_tx.id} created successfully.")

            # >>> COMMIT은 이제 Repository 내부에서 처리되어야 함 <<<
            # await session.commit()
            # logger.info(f"Rollback transaction {created_tx.id} committed successfully.")

        except IntegrityError as e:
            logger.error(f"Integrity error during rollback {rollback_reference_id}: {e}")
            # 멱등성 재확인
            # 주입된 self.wallet_repo 사용
            existing_rb_after_error = await self.wallet_repo.get_transaction_by_reference(rollback_reference_id, partner_id)
            if existing_rb_after_error:
                 logger.warning(f"Duplicate rollback transaction confirmed after integrity error: {rollback_reference_id}")
                 return await self._create_transaction_response(existing_rb_after_error)
            raise DuplicateTransactionError(f"Potential duplicate rollback transaction after rollback: {rollback_reference_id}") from e
        except (WalletNotFoundError, TransactionNotFoundError, WalletOperationError) as e:
            logger.error(f"Business logic error during rollback {rollback_reference_id}: {e}")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error during rollback {rollback_reference_id}: {e}")
            raise WalletOperationError(f"Failed to process rollback: {request.original_reference_id}") from e

        # 트랜잭션 성공 후 처리
        if created_tx and updated_balance is not None and player_id_for_cache and partner_id_for_cache:
            # 캐시 무효화
            await self.invalidate_wallet_cache(player_id_for_cache, partner_id_for_cache)
            # 이벤트 발행
            await self._publish_transaction_event(created_tx, updated_balance)
            return await self._create_transaction_response(created_tx)
        else:
            logger.error(f"Rollback completed for {rollback_reference_id} but failed to get necessary data for response/event.")
            raise WalletOperationError(f"Failed to finalize rollback operation: {request.original_reference_id}")


    async def get_player_transactions(
        self,
        player_id: UUID,
        partner_id: UUID,
        tx_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 100
    ) -> Tuple[List[Transaction], int]:
        """ 특정 플레이어의 트랜잭션 목록 조회 """
        # 세션 팩토리 사용 제거, 주입된 repo 사용
        # async with self.read_db_factory() as session:
            # wallet_repo = WalletRepository(session)
        # 주입된 self.wallet_repo 사용
        transactions, total_count = await self.wallet_repo.get_transactions(
            player_id=player_id,
            partner_id=partner_id,
            tx_type=tx_type,
            start_date=start_date,
            end_date=end_date,
            skip=skip,
            limit=limit
        )
        return transactions, total_count

    def _generate_wallet_cache_key(self, player_id: UUID, partner_id: UUID) -> str:
        """ 지갑 캐시 키 생성 """
        return f"wallet:{partner_id}:{player_id}"

    async def invalidate_wallet_cache(self, player_id: UUID, partner_id: UUID) -> None:
        """ 지갑 캐시 무효화 """
        if not self.redis:
            return
        cache_key = self._generate_wallet_cache_key(player_id, partner_id)
        try:
            deleted_count = await self.redis.delete(cache_key)
            if deleted_count > 0:
                logger.info(f"Wallet cache invalidated for key: {cache_key}")
            # else: # 키가 없어도 로깅할 필요는 없을 수 있음
            #     logger.debug(f"Wallet cache key not found for invalidation: {cache_key}")
        except Exception as e:
            logger.error(f"Failed to invalidate wallet cache for key {cache_key}: {e}")

    async def _publish_transaction_event(self, transaction: Transaction, updated_balance: Decimal) -> None:
        """ 트랜잭션 완료 및 잔액 변경 이벤트 발행 """
        try:
            # TransactionCompletedEvent 발행
            tx_event_data = {
                "transaction_id": str(transaction.id),
                "reference_id": transaction.reference_id,
                "player_id": str(transaction.player_id),
                "partner_id": str(transaction.partner_id),
                "wallet_id": str(transaction.wallet_id),
                "transaction_type": transaction.transaction_type.value,
                "amount": float(transaction.amount), # JSON 호환 위해 float 사용
                "currency": transaction.currency,
                "status": transaction.status.value,
                "timestamp": transaction.created_at.isoformat() if transaction.created_at else datetime.now(timezone.utc).isoformat(),
                "metadata": transaction.transaction_metadata
            }
            # JSON 직렬화 가능한지 확인 (선택적이지만 권장)
            try:
                 json.dumps(tx_event_data)
            except TypeError as e:
                 logger.error(f"Failed to serialize TransactionCompletedEvent data for tx {transaction.id}: {e}")
                 tx_event_data["metadata"] = {"error": "Metadata serialization failed"} # 안전한 값으로 대체

            tx_event = TransactionCompletedEvent(**tx_event_data)
            await publish_event(DomainEventType.TRANSACTION_COMPLETED, tx_event)
            logger.info(f"Published TransactionCompletedEvent for tx {transaction.id}")

            # WalletBalanceChangedEvent 발행
            balance_event_data = {
                "wallet_id": str(transaction.wallet_id),
                "player_id": str(transaction.player_id),
                "partner_id": str(transaction.partner_id),
                "new_balance": float(updated_balance), # JSON 호환 위해 float 사용
                "currency": transaction.currency,
                "transaction_id": str(transaction.id),
                "transaction_type": transaction.transaction_type.value,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            balance_event = WalletBalanceChangedEvent(**balance_event_data)
            await publish_event(DomainEventType.WALLET_BALANCE_CHANGED, balance_event)
            logger.info(f"Published WalletBalanceChangedEvent for wallet {transaction.wallet_id} after tx {transaction.id}")

        except Exception as e:
            # 이벤트 발행 실패는 로깅만 하고 트랜잭션 자체를 실패시키지는 않음
            logger.error(f"Failed to publish domain event for tx {transaction.id}: {e}")

    async def _create_transaction_response(self, transaction: Transaction) -> TransactionResponse:
        """ Transaction 모델로부터 TransactionResponse 생성 """
        try:
            amount = transaction.amount # 프로퍼티 접근 (복호화 시도)
        except Exception as e:
            logger.error(f"Failed to decrypt amount for transaction response {transaction.id}: {e}")
            # 복호화 실패 시 응답에 어떻게 표시할지 결정 필요
            amount = Decimal('-1.00') # 예: 오류 표시 값
            # 또는 None으로 처리하거나 에러 발생 등

        return TransactionResponse(
            transaction_id=transaction.id,
            reference_id=transaction.reference_id,
            player_id=transaction.player_id,
            partner_id=transaction.partner_id,
            wallet_id=transaction.wallet_id,
            transaction_type=transaction.transaction_type,
            amount=amount,
            currency=transaction.currency,
            status=transaction.status,
            original_balance=transaction.original_balance,
            updated_balance=transaction.updated_balance,
            created_at=transaction.created_at or datetime.now(timezone.utc), # None 방지
            balance=transaction.updated_balance,  # 추가: 필수 필드
            timestamp=transaction.created_at or datetime.now(timezone.utc),  # 추가: 필수 필드
            metadata=transaction.transaction_metadata # 필드 이름 확인: transaction_metadata -> metadata
        )

    async def _get_partner(self, partner_id: UUID, session: AsyncSession) -> Partner:
        """ Helper to get partner, raising specific exception if not found """
        partner_repo = PartnerRepository(session)
        try:
            return await partner_repo.get_partner_by_id(partner_id)
        except NoResultFound:
            raise PartnerNotFoundError(f"Partner with ID {partner_id} not found")