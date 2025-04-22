from fastapi import APIRouter, Depends, BackgroundTasks, Body, Query, Path, status
from sqlalchemy.orm import Session
from typing import Optional, List
from decimal import Decimal
import logging

from backend.api.dependencies.db import get_db
from backend.api.dependencies.auth import get_current_partner_id, verify_permissions
from backend.api.dependencies.common import common_pagination_params, parse_date_range
from backend.models.schemas.wallet import (
    BalanceRequest, BalanceResponse, 
    TransactionRequest, TransactionResponse, TransactionList,
    WalletActionResponse, PlayerWalletResponse
)
from backend.services.wallet.wallet_service import WalletService
from backend.services.aml.aml_service import analyze_transaction
from backend.i18n import Translator, get_translator
from backend.api.errors.exceptions import (
    ResourceNotFoundException, ForbiddenException, InvalidRequestException,
    InsufficientFundsException, DuplicateResourceException
)

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/{player_id}/balance", response_model=BalanceResponse)
async def get_player_balance(
    player_id: str = Path(..., description="플레이어 ID"),
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """
    플레이어의 지갑 잔액을 조회합니다.
    
    파트너는 자신의 플레이어의 지갑만 조회할 수 있습니다.
    """
    # 지갑 조회 권한 확인
    await verify_permissions("wallet.read")
    
    wallet_service = WalletService(db, translator)
    
    try:
        # 지갑 조회
        wallet = await wallet_service.get_wallet_by_player_and_partner(player_id, partner_id)
        
        if not wallet:
            raise ResourceNotFoundException("Wallet", player_id)
        
        # 응답 생성
        return BalanceResponse(
            status="OK",
            balance=wallet.balance,
            currency=wallet.currency,
            player_id=player_id,
            partner_id=partner_id
        )
    except ResourceNotFoundException:
        raise
    except Exception as e:
        logger.error(f"Failed to get balance for player {player_id}: {e}")
        raise InvalidRequestException(str(e))

@router.post("/{player_id}/deposit", response_model=WalletActionResponse)
async def deposit_funds(
    player_id: str,
    request: TransactionRequest,
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator)
):
    """
    플레이어의 지갑에 자금을 입금합니다.
    
    파트너는 자신의 플레이어의 지갑만 입금할 수 있습니다.
    """
    # 입금 권한 확인
    await verify_permissions("wallet.deposit")
    
    wallet_service = WalletService(db, translator)
    
    try:
        # 자금 입금 처리
        response = await wallet_service.credit_funds(
            player_id=player_id,
            partner_id=partner_id,
            amount=Decimal(str(request.amount)),
            transaction_id=request.transaction_id,
            transaction_type="deposit",
            metadata=request.metadata
        )
        
        # AML 분석 배경 작업 추가
        if response and hasattr(response, 'transaction_id'):
            background_tasks.add_task(
                analyze_transaction, 
                transaction_id=response.transaction_id, 
                db=db
            )
        
        logger.info(f"Deposit for player {player_id}: {request.amount} {response.currency if response else 'Unknown'}")
        
        return response
    except DuplicateResourceException:
        # 멱등성 처리: 이미 처리된 트랜잭션은 현재 상태 반환
        tx = await wallet_service.get_transaction_by_id(request.transaction_id)
        if tx:
            wallet = await wallet_service.get_wallet_by_player_and_partner(player_id, partner_id)
            if wallet:
                return WalletActionResponse(
                    status="OK",
                    balance=wallet.balance,
                    currency=wallet.currency,
                    transaction_id=request.transaction_id,
                    player_id=player_id,
                    partner_id=partner_id,
                    amount=tx.amount,
                    type=tx.transaction_type
                )
        raise
    except Exception as e:
        logger.error(f"Failed to deposit funds for player {player_id}: {e}")
        if "Duplicate transaction" in str(e):
            raise DuplicateResourceException("Transaction", request.transaction_id)
        raise InvalidRequestException(str(e))

@router.post("/{player_id}/withdraw", response_model=WalletActionResponse)
async def withdraw_funds(
    player_id: str,
    request: TransactionRequest,
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator)
):
    """
    플레이어의 지갑에서 자금을 출금합니다.
    
    파트너는 자신의 플레이어의 지갑만 출금할 수 있습니다.
    """
    # 출금 권한 확인
    await verify_permissions("wallet.withdraw")
    
    wallet_service = WalletService(db, translator)
    
    try:
        # 자금 출금 처리
        response = await wallet_service.debit_funds(
            player_id=player_id,
            partner_id=partner_id,
            amount=Decimal(str(request.amount)),
            transaction_id=request.transaction_id,
            transaction_type="withdrawal",
            metadata=request.metadata
        )
        
        # AML 분석 배경 작업 추가
        if response and hasattr(response, 'transaction_id'):
            background_tasks.add_task(
                analyze_transaction, 
                transaction_id=response.transaction_id, 
                db=db
            )
        
        logger.info(f"Withdrawal for player {player_id}: {request.amount} {response.currency if response else 'Unknown'}")
        
        return response
    except Exception as e:
        logger.error(f"Failed to withdraw funds for player {player_id}: {e}")
        if "Insufficient balance" in str(e):
            raise InsufficientFundsException()
        elif "Duplicate transaction" in str(e):
            raise DuplicateResourceException("Transaction", request.transaction_id)
        elif "Wallet not found" in str(e):
            raise ResourceNotFoundException("Wallet", player_id)
        raise InvalidRequestException(str(e))

@router.post("/{player_id}/bet", response_model=WalletActionResponse)
async def place_bet(
    player_id: str,
    request: TransactionRequest,
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator)
):
    """
    플레이어의 지갑에서 베팅 금액을 차감합니다.
    
    파트너는 자신의 플레이어의 지갑만 사용할 수 있습니다.
    """
    # 베팅 권한 확인
    await verify_permissions("wallet.bet")
    
    wallet_service = WalletService(db, translator)
    
    try:
        # 베팅 처리 (내부적으로 차감(debit) 로직 사용)
        response = await wallet_service.debit_funds(
            player_id=player_id,
            partner_id=partner_id,
            amount=Decimal(str(request.amount)),
            transaction_id=request.transaction_id,
            transaction_type="bet",
            game_id=request.game_id,
            metadata=request.metadata
        )
        
        # AML 분석 배경 작업 추가
        if response and hasattr(response, 'transaction_id'):
            background_tasks.add_task(
                analyze_transaction, 
                transaction_id=response.transaction_id, 
                db=db
            )
        
        logger.info(f"Bet placed for player {player_id}: {request.amount} {response.currency if response else 'Unknown'}")
        
        return response
    except Exception as e:
        logger.error(f"Failed to place bet for player {player_id}: {e}")
        if "Insufficient balance" in str(e):
            raise InsufficientFundsException()
        elif "Duplicate transaction" in str(e):
            raise DuplicateResourceException("Transaction", request.transaction_id)
        elif "Wallet not found" in str(e):
            raise ResourceNotFoundException("Wallet", player_id)
        raise InvalidRequestException(str(e))

@router.post("/{player_id}/win", response_model=WalletActionResponse)
async def credit_win(
    player_id: str,
    request: TransactionRequest,
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator)
):
    """
    플레이어의 지갑에 승리 금액을 추가합니다.
    
    파트너는 자신의 플레이어의 지갑만 사용할 수 있습니다.
    """
    # 승리 금액 추가 권한 확인
    await verify_permissions("wallet.win")
    
    wallet_service = WalletService(db, translator)
    
    try:
        # 승리 금액 추가 처리 (내부적으로 추가(credit) 로직 사용)
        response = await wallet_service.credit_funds(
            player_id=player_id,
            partner_id=partner_id,
            amount=Decimal(str(request.amount)),
            transaction_id=request.transaction_id,
            transaction_type="win",
            game_id=request.game_id,
            metadata=request.metadata
        )
        
        # AML 분석 배경 작업 추가
        if response and hasattr(response, 'transaction_id'):
            background_tasks.add_task(
                analyze_transaction, 
                transaction_id=response.transaction_id, 
                db=db
            )
        
        logger.info(f"Win credited for player {player_id}: {request.amount} {response.currency if response else 'Unknown'}")
        
        return response
    except Exception as e:
        logger.error(f"Failed to credit win for player {player_id}: {e}")
        if "Duplicate transaction" in str(e):
            raise DuplicateResourceException("Transaction", request.transaction_id)
        elif "Wallet not found" in str(e):
            raise ResourceNotFoundException("Wallet", player_id)
        raise InvalidRequestException(str(e))

@router.post("/{player_id}/cancel", response_model=WalletActionResponse)
async def cancel_transaction(
    player_id: str,
    request: TransactionRequest,
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db),
    translator: Translator = Depends(get_translator)
):
    """
    트랜잭션을 취소합니다.
    
    파트너는 자신의 플레이어와 관련된 트랜잭션만 취소할 수 있습니다.
    """
    # 트랜잭션 취소 권한 확인
    await verify_permissions("wallet.cancel")
    
    wallet_service = WalletService(db, translator)
    
    if not request.ref_transaction_id:
        raise InvalidRequestException("Original transaction ID (ref_transaction_id) is required")
    
    try:
        # 트랜잭션 취소 처리
        response = await wallet_service.cancel_transaction(
            player_id=player_id,
            partner_id=partner_id,
            transaction_id=request.transaction_id,
            original_transaction_id=request.ref_transaction_id
        )
        
        logger.info(f"Transaction {request.ref_transaction_id} canceled for player {player_id}")
        
        return response
    except Exception as e:
        logger.error(f"Failed to cancel transaction for player {player_id}: {e}")
        if "Transaction not found" in str(e):
            raise ResourceNotFoundException("Transaction", request.ref_transaction_id)
        elif "already processed" in str(e):
            raise DuplicateResourceException("Cancel Transaction", request.ref_transaction_id)
        elif "Insufficient balance" in str(e):
            raise InsufficientFundsException()
        raise InvalidRequestException(str(e))

@router.get("/{player_id}/transactions", response_model=TransactionList)
async def get_player_transactions(
    player_id: str = Path(..., description="플레이어 ID"),
    transaction_type: Optional[str] = Query(None, description="거래 유형으로 필터링"),
    transaction_id: Optional[str] = Query(None, description="거래 ID로 검색"),
    date_range: dict = Depends(parse_date_range),
    pagination: dict = Depends(common_pagination_params),
    partner_id: str = Depends(get_current_partner_id),
    db: Session = Depends(get_db)
):
    """
    플레이어의 거래 내역을 조회합니다.
    
    파트너는 자신의 플레이어의 거래 내역만 조회할 수 있습니다.
    """
    # 거래 내역 조회 권한 확인
    await verify_permissions("wallet.transactions.read")
    
    wallet_service = WalletService(db)
    
    # 거래 내역 조회
    transactions, total = await wallet_service.get_player_transactions(
        player_id=player_id,
        partner_id=partner_id,
        transaction_type=transaction_type,
        transaction_id=transaction_id,
        start_date=date_range["start_date"],
        end_date=date_range["end_date"],
        skip=pagination["skip"],
        limit=pagination["limit"]
    )
    
    # 응답 생성
    items = []
    for tx in transactions:
        items.append(TransactionResponse(
            id=tx.id,
            transaction_id=tx.transaction_id,
            player_id=tx.player_id,
            partner_id=tx.partner_id,
            game_id=tx.game_id,
            transaction_type=tx.transaction_type,
            amount=tx.amount,
            currency=tx.currency,
            status=tx.status,
            original_balance=tx.original_balance,
            updated_balance=tx.updated_balance,
            created_at=tx.created_at,
            updated_at=tx.updated_at,
            ref_transaction_id=tx.ref_transaction_id,
            metadata=tx.transaction_metadata
        ))
    
    return TransactionList(
        items=items,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"]
    )