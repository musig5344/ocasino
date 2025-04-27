from fastapi import APIRouter, Depends, BackgroundTasks, Body, Path, status, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List, Tuple, Annotated, Any, Dict, Union
from decimal import Decimal
import logging
from datetime import datetime
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

# Common Schemas (Updated Import)
from backend.core.schemas import ErrorResponse, StandardResponse, PaginatedResponse, ErrorResponseDetail

# Wallet Dependencies
from backend.wallet.dependencies import get_aml_service, get_wallet_service
from backend.services.aml.aml_service import AMLService
from backend.services.wallet.wallet_service import WalletService

# Core Dependencies
from backend.core.dependencies import (
    get_db,
    get_current_partner_id,
    require_permission,
    get_current_permissions,
    common_pagination_params,
) # 새로운 공통 의존성 사용

# Wallet Schemas
from backend.schemas.wallet import (
    BalanceResponse,
    TransactionRequest, TransactionResponse, TransactionList,
    WalletActionResponse, PlayerWalletResponse, RollbackRequest, DebitRequest, CreditRequest
)

# Services are now implicitly imported via dependencies
# from backend.services.wallet.wallet_service import WalletService 
# from backend.services.aml.aml_service import AMLService
from backend.i18n import Translator, get_translator
from backend.core.exceptions import (
    WalletNotFoundError, AuthorizationError, InvalidInputError, 
    InsufficientFundsError, DuplicateTransactionError, CurrencyMismatchError, 
    InvalidTransactionStatusError, ValidationError
)

# Standard Response Utils
from backend.utils.response import success_response, paginated_response

router = APIRouter(tags=["Wallet Operations"]) # Prefix removed, will be handled in api.py
logger = logging.getLogger(__name__)

# 공통 유틸리티 함수
async def schedule_aml_analysis(
    background_tasks: BackgroundTasks,
    aml_service: AMLService,
    response: Union[TransactionResponse, WalletActionResponse],
    db: AsyncSession
) -> None:
    """AML 분석을 위한 백그라운드 태스크를 스케줄링합니다."""
    if not response:
        return
        
    transaction_id = getattr(response, 'id', None) or getattr(response, 'transaction_id', None)
    
    if transaction_id:
        background_tasks.add_task(
            aml_service.analyze_transaction_background,
            transaction_id=transaction_id,
            db=db
        )

def log_transaction(action: str, player_id: UUID, request_amount: Decimal, response_currency: str) -> None:
    """트랜잭션 로그를 기록합니다."""
    logger.info(f"{action} for player {player_id}: {request_amount} {response_currency or 'Unknown'}")

@router.get(
    "/{player_id}/balance", 
    response_model=StandardResponse[BalanceResponse],
    summary="플레이어 지갑 잔액 조회",
    description="""
    지정된 플레이어 ID의 현재 지갑 잔액과 통화를 조회합니다. 
    파트너는 자신이 관리하는 플레이어(`partner_id` 일치)의 잔액만 조회할 수 있습니다.
    """,
    responses={
        status.HTTP_200_OK: {"description": "잔액 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 플레이어 지갑 조회 권한 없음"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정한 플레이어 ID에 해당하는 지갑을 찾을 수 없음"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "잔액 조회 중 내부 서버 오류 발생"}
    }
)
async def get_player_balance(
    player_id: UUID = Path(..., description="잔액을 조회할 플레이어의 고유 ID", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    wallet_service: WalletService = Depends(get_wallet_service),
    translator: Translator = Depends(get_translator),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    플레이어의 현재 지갑 잔액을 조회합니다.
    
    - **player_id**: 조회 대상 플레이어의 UUID.
    
    **권한 요구사항:** `wallet.balance.read` (또는 유사 권한)
    """
    if "wallet.balance.read" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to read wallet balance")
        
    wallet = await wallet_service.get_wallet_by_player_and_partner(player_id, requesting_partner_id)
    
    balance_data = BalanceResponse(
        balance=wallet.balance,
        currency=wallet.currency,
        player_id=player_id,
        partner_id=requesting_partner_id,
        timestamp=datetime.utcnow()
    )
    return success_response(data=balance_data)

@router.post(
    "/{player_id}/deposit", 
    response_model=StandardResponse[WalletActionResponse], 
    status_code=status.HTTP_201_CREATED, 
    summary="플레이어 지갑 입금 처리",
    description="""
    지정된 플레이어 지갑에 자금을 입금(Credit)합니다. 
    `reference_id`는 이 입금 요청을 고유하게 식별하며, 멱등성 키로 사용됩니다.
    
    - 동일한 `reference_id`로 재요청 시, 이미 성공적으로 처리된 경우 기존 트랜잭션 정보를 포함하여 **200 OK**를 반환합니다.
    - 파트너는 자신이 관리하는 플레이어(`partner_id` 일치)에게만 입금할 수 있습니다.
    - 입금 성공 시 AML 분석을 위한 백그라운드 작업이 예약될 수 있습니다.
    """,
    responses={
        status.HTTP_201_CREATED: {"description": "입금 성공 및 트랜잭션 생성됨"},
        status.HTTP_200_OK: {"description": "이미 처리된 트랜잭션 (멱등성 보장)"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 플레이어 지갑 입금 권한 없음 또는 파트너 불일치"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정한 플레이어 ID에 해당하는 지갑을 찾을 수 없음"},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "트랜잭션 참조 ID(reference_id)가 이미 사용 중 (다른 요청 또는 완료되지 않은 요청)"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "요청 데이터 유효성 오류 (금액, 통화 형식 등) 또는 통화 불일치"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "입금 처리 중 내부 서버 오류 발생"}
    }
)
async def deposit_funds(
    player_id: UUID = Path(..., description="입금 대상 플레이어의 고유 ID", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    request: TransactionRequest = Body(..., example={
        "reference_id": "deposit_tx_1699887766",
        "amount": "100.50",
        "currency": "KRW",
        "metadata": {"source": "Bank Transfer", "channel": "mobile_app"}
    }),
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    wallet_service: WalletService = Depends(get_wallet_service),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator),
    aml_service: AMLService = Depends(get_aml_service),
    db: AsyncSession = Depends(get_db),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    플레이어 지갑에 자금을 입금(Credit)합니다.
    
    - **player_id**: 입금 대상 플레이어의 UUID.
    - **request**: 입금 요청 정보 (TransactionRequest 스키마).
    
    **권한 요구사항:** `wallet.deposit`
    """
    if "wallet.deposit" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to deposit funds")
        
    credit_request = CreditRequest(
        player_id=player_id,
        reference_id=request.reference_id,
        amount=request.amount,
        currency=request.currency,
        metadata=request.metadata
    )
    response, created = await wallet_service.credit(
        request=credit_request,
        partner_id=requesting_partner_id
    )
    
    status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    message = "Deposit successful." if created else "Deposit request already processed."
    
    if created:
        await schedule_aml_analysis(background_tasks, aml_service, response, db)
        log_transaction("Deposit", player_id, request.amount, response.currency)
    else:
        logger.info(f"Idempotent deposit request processed: {request.reference_id}")

    response_content = success_response(data=response, message=message).model_dump()
    return JSONResponse(content=response_content, status_code=status_code)

@router.post(
    "/{player_id}/withdraw", 
    response_model=StandardResponse[WalletActionResponse],
    status_code=status.HTTP_200_OK,
    summary="플레이어 지갑 출금 처리",
    description="""
    지정된 플레이어 지갑에서 자금을 출금(Debit)합니다. 
    `reference_id`는 이 출금 요청을 고유하게 식별하며, 멱등성 키로 사용됩니다.
    
    - 동일한 `reference_id`로 재요청 시, 이미 성공적으로 처리된 경우 기존 트랜잭션 정보를 포함하여 **200 OK**를 반환합니다.
    - 파트너는 자신이 관리하는 플레이어(`partner_id` 일치)에게서만 출금할 수 있습니다.
    - 잔액 부족 시 **402 Payment Required** 오류를 반환합니다.
    - 출금 성공 시 AML 분석을 위한 백그라운드 작업이 예약될 수 있습니다.
    """,
    responses={
        status.HTTP_200_OK: {"description": "출금 성공 또는 이미 처리된 트랜잭션 (멱등성 보장)"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_402_PAYMENT_REQUIRED: {"model": ErrorResponse, "description": "지갑 잔액 부족"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 플레이어 지갑 출금 권한 없음 또는 파트너 불일치"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정한 플레이어 ID에 해당하는 지갑을 찾을 수 없음"},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "트랜잭션 참조 ID(reference_id)가 이미 사용 중 (다른 요청 또는 완료되지 않은 요청)"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "요청 데이터 유효성 오류 (금액, 통화 형식 등) 또는 통화 불일치"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "출금 처리 중 내부 서버 오류 발생"}
    }
)
async def withdraw_funds(
    player_id: UUID = Path(..., description="출금 대상 플레이어의 고유 ID", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    request: TransactionRequest = Body(..., example={
        "reference_id": "withdraw_tx_1699887800",
        "amount": "50.00",
        "currency": "KRW",
        "metadata": {"destination": "User Bank Account **** **** 1234", "reason": "Player withdrawal request"}
    }),
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    wallet_service: WalletService = Depends(get_wallet_service),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator),
    aml_service: AMLService = Depends(get_aml_service),
    db: AsyncSession = Depends(get_db),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    플레이어 지갑에서 자금을 출금(Debit)합니다.
    
    - **player_id**: 출금 대상 플레이어의 UUID.
    - **request**: 출금 요청 정보 (TransactionRequest 스키마).
    
    **권한 요구사항:** `wallet.withdraw`
    """
    if "wallet.withdraw" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to withdraw funds")

    debit_request = DebitRequest(
        player_id=player_id,
        reference_id=request.reference_id,
        amount=request.amount,
        currency=request.currency,
        metadata=request.metadata
    )
    response, created = await wallet_service.debit(
        request=debit_request,
        partner_id=requesting_partner_id,
        transaction_type="WITHDRAW"
    )
    
    status_code = status.HTTP_200_OK
    message = "Withdrawal successful." if created else "Withdrawal request already processed."

    if created:
        await schedule_aml_analysis(background_tasks, aml_service, response, db)
        log_transaction("Withdrawal", player_id, request.amount, response.currency)
    else:
        logger.info(f"Idempotent withdrawal request processed: {request.reference_id}")

    response_content = success_response(data=response, message=message).model_dump()
    return JSONResponse(content=response_content, status_code=status_code)

@router.post(
    "/{player_id}/bet",
    response_model=StandardResponse[TransactionResponse], 
    status_code=status.HTTP_200_OK,
    summary="플레이어 게임 베팅 처리",
    description="""
    플레이어의 게임 베팅을 처리하고 지갑 잔액을 차감(Debit)합니다.
    `reference_id`는 이 베팅 요청을 고유하게 식별하며, 멱등성 키로 사용됩니다.
    
    - 동일한 `reference_id`로 재요청 시, 이미 성공적으로 처리된 경우 기존 트랜잭션 정보를 포함하여 **200 OK**를 반환합니다.
    - 파트너는 자신이 관리하는 플레이어(`partner_id` 일치)의 베팅만 처리할 수 있습니다.
    - 잔액 부족 시 **402 Payment Required** 오류를 반환합니다.
    - 베팅 성공 시 AML 분석을 위한 백그라운드 작업이 예약될 수 있습니다.
    """,
    tags=["Game Transactions"],
    responses={
        status.HTTP_200_OK: {"description": "베팅 성공 또는 이미 처리된 베팅 트랜잭션 (멱등성 보장)"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_402_PAYMENT_REQUIRED: {"model": ErrorResponse, "description": "지갑 잔액 부족"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 플레이어 베팅 처리 권한 없음 또는 파트너 불일치"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정한 플레이어 ID에 해당하는 지갑을 찾을 수 없음"},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "트랜잭션 참조 ID(reference_id)가 이미 사용 중 (다른 요청 또는 완료되지 않은 요청)"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "요청 데이터 유효성 오류 (금액, 통화 형식 등) 또는 통화 불일치"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "베팅 처리 중 내부 서버 오류 발생"}
    }
)
async def place_bet(
    player_id: UUID = Path(..., description="베팅 플레이어의 고유 ID", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    request: TransactionRequest = Body(..., example={
        "reference_id": "bet_round_1699887900_a",
        "amount": "10.00",
        "currency": "KRW",
        "metadata": {"game_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef", "round_id": "round_556677", "bet_type": "straight_up"}
    }),
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    wallet_service: WalletService = Depends(get_wallet_service),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator),
    aml_service: AMLService = Depends(get_aml_service),
    db: AsyncSession = Depends(get_db),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    플레이어의 게임 베팅을 처리하고 지갑 잔액을 차감(Debit)합니다.
    
    - **player_id**: 베팅 플레이어의 UUID.
    - **request**: 베팅 요청 정보 (TransactionRequest 스키마).
    
    **권한 요구사항:** `wallet.bet`
    """
    if "wallet.bet" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to place bets")
        
    debit_request = DebitRequest(
        player_id=player_id,
        reference_id=request.reference_id,
        amount=request.amount,
        currency=request.currency,
        metadata=request.metadata
    )
    response, created = await wallet_service.debit(
        request=debit_request,
        partner_id=requesting_partner_id,
        transaction_type="BET"
    )

    status_code = status.HTTP_200_OK
    message = "Bet placed successfully." if created else "Bet request already processed."
    
    if created:
        await schedule_aml_analysis(background_tasks, aml_service, response, db)
        log_transaction("Bet", player_id, request.amount, response.currency)
    else:
        logger.info(f"Idempotent bet request processed: {request.reference_id}")
        
    response_content = success_response(data=response, message=message).model_dump()
    return JSONResponse(content=response_content, status_code=status_code)

@router.post(
    "/{player_id}/win", 
    response_model=StandardResponse[TransactionResponse], 
    status_code=status.HTTP_201_CREATED, 
    summary="플레이어 게임 승리 기록",
    description="""
    플레이어의 게임 승리 결과를 기록하고 지갑 잔액을 증가(Credit)시킵니다.
    `reference_id`는 이 승리 기록 요청을 고유하게 식별하며, 멱등성 키로 사용됩니다.
    
    - 동일한 `reference_id`로 재요청 시, 이미 성공적으로 처리된 경우 기존 트랜잭션 정보를 포함하여 **200 OK**를 반환합니다.
    - 파트너는 자신이 관리하는 플레이어(`partner_id` 일치)의 승리만 기록할 수 있습니다.
    - 승리 기록 성공 시 AML 분석을 위한 백그라운드 작업이 예약될 수 있습니다.
    """,
    tags=["Game Transactions"],
    responses={
        status.HTTP_201_CREATED: {"description": "승리 기록 성공 및 트랜잭션 생성됨"},
        status.HTTP_200_OK: {"description": "이미 처리된 트랜잭션 (멱등성 보장)"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 플레이어 승리 기록 권한 없음 또는 파트너 불일치"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정한 플레이어 ID에 해당하는 지갑을 찾을 수 없음"},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "트랜잭션 참조 ID(reference_id)가 이미 사용 중 (다른 요청 또는 완료되지 않은 요청)"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "요청 데이터 유효성 오류 (금액, 통화 형식 등) 또는 통화 불일치"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "승리 기록 중 내부 서버 오류 발생"}
    }
)
async def record_win(
    player_id: UUID = Path(..., description="승리 기록 대상 플레이어의 고유 ID", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    request: TransactionRequest = Body(..., example={
        "reference_id": "win_round_1699887900_a",
        "amount": "25.50",
        "currency": "KRW",
        "metadata": {"game_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef", "round_id": "round_556677", "payout": 2.55}
    }),
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    wallet_service: WalletService = Depends(get_wallet_service),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator),
    aml_service: AMLService = Depends(get_aml_service),
    db: AsyncSession = Depends(get_db),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    플레이어의 게임 승리 결과를 기록하고 지갑 잔액을 증가(Credit)시킵니다.
    
    - **player_id**: 승리 기록 대상 플레이어의 UUID.
    - **request**: 승리 기록 요청 정보 (TransactionRequest 스키마).
    
    **권한 요구사항:** `wallet.win`
    """
    if "wallet.win" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to record wins")
        
    credit_request = CreditRequest(
        player_id=player_id,
        reference_id=request.reference_id,
        amount=request.amount,
        currency=request.currency,
        metadata=request.metadata
    )
    response, created = await wallet_service.credit(
        request=credit_request,
        partner_id=requesting_partner_id,
        transaction_type="WIN"
    )

    status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    message = "Win recorded successfully." if created else "Win request already processed."

    if created:
        await schedule_aml_analysis(background_tasks, aml_service, response, db)
        log_transaction("Win", player_id, request.amount, response.currency)
    else:
        logger.info(f"Idempotent win request processed: {request.reference_id}")

    response_content = success_response(data=response, message=message).model_dump()
    return JSONResponse(content=response_content, status_code=status_code)

@router.post(
    "/{player_id}/rollback", 
    response_model=StandardResponse[TransactionResponse],
    status_code=status.HTTP_200_OK,
    summary="트랜잭션 롤백 처리",
    description="""
    이전에 발생한 특정 트랜잭션(주로 베팅 또는 승리)의 효과를 취소(Rollback)합니다. 
    예를 들어, 베팅 롤백 시 차감되었던 금액이 플레이어에게 환불됩니다.
    
    - `reference_id`는 이 롤백 요청 자체를 고유하게 식별하며, 멱등성 키로 사용됩니다.
    - `original_reference_id`는 롤백 대상이 되는 원래 트랜잭션(베팅 또는 승리)의 `reference_id`입니다.
    - 동일한 `reference_id` (롤백 요청 ID)로 재요청 시, 이미 성공적으로 처리된 경우 기존 롤백 트랜잭션 정보를 포함하여 **200 OK**를 반환합니다.
    - 파트너는 자신이 관리하는 플레이어(`partner_id` 일치)의 트랜잭션만 롤백할 수 있습니다.
    - 원본 트랜잭션이 존재하지 않거나 이미 롤백된 경우 오류가 발생합니다.
    - 롤백 성공 시 AML 분석을 위한 백그라운드 작업이 예약될 수 있습니다.
    """,
    tags=["Wallet Transactions"],
    responses={
        status.HTTP_200_OK: {"description": "롤백 성공 또는 이미 처리된 롤백 트랜잭션 (멱등성 보장)"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 트랜잭션 롤백 권한 없음 또는 파트너 불일치"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "원본 트랜잭션(`original_reference_id`) 또는 플레이어/지갑을 찾을 수 없음"},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "이미 롤백된 트랜잭션이거나 롤백 불가능한 상태 / 또는 롤백 요청 참조 ID 중복"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "요청 데이터 유효성 오류"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "롤백 처리 중 내부 서버 오류 발생"}
    }
)
async def rollback_transaction(
    player_id: UUID = Path(..., description="롤백 대상 플레이어의 고유 ID", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    request: RollbackRequest = Body(..., example={
        "reference_id": "rollback_bet_round_1699887900_a",
        "original_reference_id": "bet_round_1699887900_a",
        "metadata": {"reason": "Game round cancelled due to technical issue"}
    }),
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    wallet_service: WalletService = Depends(get_wallet_service),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    translator: Translator = Depends(get_translator),
    aml_service: AMLService = Depends(get_aml_service),
    db: AsyncSession = Depends(get_db),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    특정 트랜잭션을 롤백합니다.
    
    - **player_id**: 롤백 대상 플레이어의 UUID.
    - **request**: 롤백 요청 정보 (RollbackRequest 스키마).
    
    **권한 요구사항:** `wallet.rollback`
    """
    if "wallet.rollback" not in requesting_permissions:
        raise PermissionDeniedError("Permission denied to rollback transactions")
        
    response, created = await wallet_service.rollback(
        request=request,
        partner_id=requesting_partner_id
    )
    
    status_code = status.HTTP_200_OK
    message = "Transaction rolled back successfully." if created else "Rollback request already processed."

    if created:
        await schedule_aml_analysis(background_tasks, aml_service, response, db)
        log_transaction("Rollback", player_id, response.amount, response.currency)
    else:
        logger.info(f"Idempotent rollback request processed: {request.reference_id}")

    response_content = success_response(data=response, message=message).model_dump()
    return JSONResponse(content=response_content, status_code=status_code)

@router.get(
    "/{player_id}/transactions", 
    response_model=PaginatedResponse[TransactionResponse],
    tags=["Wallet Transactions"],
    summary="플레이어 거래 내역 조회",
    description="""
    지정된 플레이어 ID의 거래 내역(입금, 출금, 베팅, 승리, 롤백 등)을 조회합니다.
    페이지네이션, 날짜 범위 필터링, 거래 유형 필터링을 지원합니다.
    
    - **파트너 (`wallet.transactions.read.self` 권한):** 자신이 관리하는 플레이어(`partner_id` 일치)의 거래 내역만 조회할 수 있습니다.
    - **관리자 (`wallet.transactions.read.all` 권한):** 모든 플레이어의 거래 내역을 조회할 수 있습니다.
    """,
    responses={
        status.HTTP_200_OK: {"description": "거래 내역 조회 성공"},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "해당 플레이어 거래 내역 조회 권한 없음 또는 파트너 불일치"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "지정한 플레이어 ID를 찾을 수 없음"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ErrorResponse, "description": "잘못된 날짜 형식 또는 필터 파라미터"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "거래 내역 조회 중 내부 서버 오류 발생"}
    }
)
async def get_player_transactions(
    player_id: UUID = Path(..., description="거래 내역을 조회할 플레이어의 고유 ID", example="f47ac10b-58cc-4372-a567-0e02b2c3d479"),
    transaction_type: Optional[str] = Query(None, description="필터링할 거래 유형(transaction_type)", example="BET", regex="^(DEPOSIT|WITHDRAW|BET|WIN|ROLLBACK|ADJUSTMENT)$", alias="type"),
    reference_id: Optional[str] = Query(None, description="특정 참조 ID(reference_id)로 필터링", example="bet_round_1699887900_a"),
    start_date: Optional[datetime] = Query(None, description="Filter start date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="Filter end date (ISO format)"),
    requesting_partner_id: UUID = Depends(get_current_partner_id),
    wallet_service: WalletService = Depends(get_wallet_service),
    pagination: Dict[str, Any] = Depends(common_pagination_params),
    translator: Translator = Depends(get_translator),
    requesting_permissions: List[str] = Depends(get_current_permissions)
):
    """
    플레이어의 거래 내역을 조회합니다.
    
    - **player_id**: 조회 대상 플레이어의 UUID.
    - **transaction_type**: 거래 유형 필터.
    - **reference_id**: 참조 ID 필터.
    - **start_date**: 조회 시작 날짜 (ISO 형식).
    - **end_date**: 조회 종료 날짜 (ISO 형식).
    
    **권한 요구사항:** `wallet.transactions.read.self` 또는 `wallet.transactions.read.all`
    """
    can_read_all = "wallet.transactions.read.all" in requesting_permissions
    can_read_self = "wallet.transactions.read.self" in requesting_permissions
    
    if not can_read_all and not can_read_self:
        raise PermissionDeniedError("Permission denied to view transactions")
        
    target_partner_id = None if can_read_all else requesting_partner_id
    
    if not can_read_all:
        try:
            await wallet_service.get_wallet_by_player_and_partner(player_id, target_partner_id)
        except WalletNotFoundError:
            raise WalletNotFoundError(f"Player {player_id} not found or access denied.")
        except AuthorizationError:
            raise PermissionDeniedError("Permission denied to view transactions for this player")

    transactions, total = await wallet_service.list_transactions(
        player_id=player_id,
        partner_id=target_partner_id,
        skip=pagination["offset"],
        limit=pagination["limit"],
        start_date=start_date,
        end_date=end_date,
        transaction_type=transaction_type,
        reference_id=reference_id
    )
    
    return paginated_response(
        items=transactions,
        total=total,
        page=pagination.get("page", 1),
        page_size=pagination["limit"]
    )

# TODO: Consider adding an endpoint for manual adjustments (Admin only)
# @router.post("/{player_id}/adjust", ...)
# async def adjust_balance(...) 