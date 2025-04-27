"""
게임 서비스
게임 통합, 세션 관리, 게임 트랜잭션 처리 등 비즈니스 로직 담당
"""
import logging
from uuid import UUID, uuid4
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta, timezone
import secrets
import hmac
import hashlib
import json
import httpx
from urllib.parse import urlencode
import redis.asyncio as redis
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status, Request

from backend.models.domain.game import Game, GameProvider, GameSession, GameTransaction
from backend.partners.models import Partner
from backend.partners.repository import PartnerRepository
from backend.repositories.game_repository import GameRepository
from backend.repositories.wallet_repository import WalletRepository
from backend.services.wallet.wallet_service import WalletService
from backend.schemas.game import (
    Game as GameSchema,
    GameCreate,
    GameUpdate,
    GameLaunchRequest,
    GameLaunchResponse
)
from backend.schemas.wallet import DebitRequest, CreditRequest, RollbackRequest
from backend.core.config import settings
from backend.core.exceptions import (
    ValidationError, AuthenticationError, NotFoundError, DatabaseError, ConflictError
)
from backend.cache.redis_cache import get_redis_client
from backend.core.service import BaseService
from backend.models.enums import GameStatus, SessionStatus
from backend.models.domain.wallet import TransactionType, TransactionStatus

logger = logging.getLogger(__name__)

# --- 상수 정의 ---
CALLBACK_TIMESTAMP_TOLERANCE_SECONDS = 300  # 5분
NONCE_EXPIRY_SECONDS = 600 # 10분

class GameNotFoundError(NotFoundError):
    """Custom exception for Game not found."""
    pass

class GameService(BaseService[Game, GameSchema, GameCreate, GameUpdate]):
    """게임 서비스"""
    
    # BaseService attributes
    service_name = "game"
    entity_name = "game"
    not_found_exception_class = GameNotFoundError
    
    def __init__(self, db: AsyncSession, redis_client: redis.Redis):
        # Initialize BaseService 
        super().__init__(
            db=db,
            model_class=Game,
            response_schema_class=GameSchema,
            create_schema_class=GameCreate,
            update_schema_class=GameUpdate
        )
        self.redis_client = redis_client
        self.game_repo = GameRepository(db)
        self.wallet_repo = WalletRepository(db)
        self.partner_repo = PartnerRepository(db)
        self.wallet_service = WalletService(db)
    
    async def get_provider(self, provider_id: UUID) -> Optional[GameProvider]:
        """
        ID로 게임 제공자 조회
        
        Args:
            provider_id: 게임 제공자 ID
            
        Returns:
            Optional[GameProvider]: 게임 제공자 객체 또는 None
        """
        return await self.game_repo.get_provider_by_id(provider_id)
    
    async def launch_game(
        self, request: GameLaunchRequest, partner_id: UUID
    ) -> GameLaunchResponse:
        """
        게임 실행 URL 생성
        
        Args:
            request: 게임 실행 요청
            partner_id: 파트너 ID
            
        Returns:
            GameLaunchResponse: 게임 실행 URL 응답
            
        Raises:
            HTTPException: 게임 또는 지갑이 존재하지 않는 경우
        """
        # 게임 조회
        game = await self.get_or_404(request.game_id)
        
        # 게임 제공자 조회
        provider = await self.get_provider(game.provider_id)
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Provider {game.provider_id} not found"
            )
        
        # 지갑 조회 (없으면 생성)
        wallet, created = await self.wallet_service.ensure_wallet_exists(
            request.player_id, partner_id, request.currency
        )
        
        # 세션 토큰 생성
        token = await self._generate_session_token()
        expires_at = datetime.utcnow() + timedelta(hours=24)
        
        # 게임 세션 생성
        session = GameSession(
            player_id=request.player_id,
            partner_id=partner_id,
            game_id=game.id,
            token=token,
            status="active",
            device_info={},
            session_data={
                "currency": request.currency,
                "language": request.language or "en",
                "return_url": str(request.return_url) if request.return_url else None
            }
        )
        
        created_session = await self.game_repo.create_session(session)
        
        # 통합 유형에 따라 게임 URL 생성
        if provider.integration_type == "direct":
            game_url = await self._create_direct_game_url(
                provider, game, token, wallet, request
            )
        elif provider.integration_type == "aggregator":
            game_url = await self._create_aggregator_game_url(
                provider, game, token, wallet, request
            )
        elif provider.integration_type == "iframe":
            game_url = await self._create_iframe_game_url(
                provider, game, token, wallet, request
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unsupported integration type: {provider.integration_type}"
            )
        
        return GameLaunchResponse(
            game_url=game_url,
            token=token,
            expires_at=expires_at
        )
    
    def _generate_session_token(self, length: int = 32) -> str:
        """
        보안 세션 토큰 생성
        
        Args:
            length: 토큰 길이
            
        Returns:
            str: 생성된 토큰
        """
        return secrets.token_hex(length // 2)
    
    async def _create_direct_game_url(
        self, 
        provider: GameProvider, 
        game: Game, 
        token: str, 
        wallet, 
        request: GameLaunchRequest
    ) -> str:
        """
        직접 통합 게임 URL 생성
        
        Args:
            provider: 게임 제공자
            game: 게임
            token: 세션 토큰
            wallet: 지갑
            request: 게임 실행 요청
            
        Returns:
            str: 게임 URL
        """
        # 파라미터 구성
        params = {
            "token": token,
            "gameCode": game.game_code,
            "currency": request.currency,
            "language": request.language or "en",
            "playerId": str(request.player_id),
            "balance": str(wallet.balance),
            "returnUrl": str(request.return_url) if request.return_url else settings.DEFAULT_RETURN_URL,
            "platform": request.device_info.get("platform", "desktop") if hasattr(request, "device_info") else "desktop"
        }
        
        # 서명 생성
        signature_data = f"{token}|{game.game_code}|{request.currency}|{str(request.player_id)}"
        signature = hmac.new(
            provider.api_secret.encode(),
            signature_data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        params["signature"] = signature
        
        # URL 구성
        base_url = f"{provider.api_endpoint}/launch"
        query_string = urlencode(params)
        
        return f"{base_url}?{query_string}"
    
    async def _create_aggregator_game_url(
        self, 
        provider: GameProvider, 
        game: Game, 
        token: str, 
        wallet, 
        request: GameLaunchRequest
    ) -> str:
        """
        어그리게이터 통합 게임 URL 생성
        
        Args:
            provider: 게임 제공자
            game: 게임
            token: 세션 토큰
            wallet: 지갑
            request: 게임 실행 요청
            
        Returns:
            str: 게임 URL
        """
        # API 요청 데이터
        data = {
            "api_key": provider.api_key,
            "token": token,
            "game_id": game.game_code,
            "currency": request.currency,
            "language": request.language or "en",
            "player_id": str(request.player_id),
            "balance": str(wallet.balance),
            "return_url": str(request.return_url) if request.return_url else settings.DEFAULT_RETURN_URL,
            "country": request.player_country if hasattr(request, "player_country") else None,
            "platform": request.device_info.get("platform", "desktop") if hasattr(request, "device_info") else "desktop"
        }
        
        # 타임스탬프 및 서명 추가
        timestamp = int(datetime.utcnow().timestamp())
        data["timestamp"] = timestamp
        
        # 서명 생성
        signature_data = f"{provider.api_key}|{token}|{game.game_code}|{timestamp}"
        signature = hmac.new(
            provider.api_secret.encode(),
            signature_data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        data["signature"] = signature
        
        # API 호출
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(f"{provider.api_endpoint}/game/launch", json=data)
                response.raise_for_status()
                result = response.json()
                
                if not result.get("success"):
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to launch game: {result.get('message', 'Unknown error')}"
                    )
                
                return result["game_url"]
        except httpx.HTTPError as e:
            logger.error(f"Failed to launch game via aggregator: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to launch game: {str(e)}"
            )
    
    async def _create_iframe_game_url(
        self, 
        provider: GameProvider, 
        game: Game, 
        token: str, 
        wallet, 
        request: GameLaunchRequest
    ) -> str:
        """
        iframe 통합 게임 URL 생성
        
        Args:
            provider: 게임 제공자
            game: 게임
            token: 세션 토큰
            wallet: 지갑
            request: 게임 실행 요청
            
        Returns:
            str: 게임 URL
        """
        # iframe URL 구성
        params = {
            "token": token,
            "gameId": game.game_code,
            "currency": request.currency,
            "lang": request.language or "en",
            "playerId": str(request.player_id),
            "homeUrl": str(request.return_url) if request.return_url else settings.DEFAULT_RETURN_URL
        }
        
        query_string = urlencode(params)
        
        # URL 반환
        return f"{settings.IFRAME_BASE_URL}/game?{query_string}"
    
    async def _get_partner_secret(self, partner_id: UUID) -> Optional[str]:
        """파트너 ID로 공유 비밀키 조회"""
        partner = await self.partner_repo.get_partner_by_id(partner_id)
        # 파트너 모델에 shared_secret 필드가 있다고 가정
        return partner.shared_secret if partner else None

    async def _verify_timestamp(self, timestamp: int):
        """타임스탬프 유효성 검증"""
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if abs(now_ts - timestamp) > CALLBACK_TIMESTAMP_TOLERANCE_SECONDS:
            logger.warning(f"Invalid timestamp received: {timestamp}, current: {now_ts}")
            raise AuthenticationError("Invalid timestamp")

    async def _verify_nonce(self, nonce: str):
        """논스 유효성 검증 및 저장"""
        redis_key = f"nonce:{nonce}"
        # NX (Not Exists) 옵션으로 설정 시도, 성공하면 1 반환 (새로운 논스)
        added = await self.redis_client.set(redis_key, "1", nx=True, ex=NONCE_EXPIRY_SECONDS)
        if not added:
            logger.warning(f"Replay attack detected with nonce: {nonce}")
            raise AuthenticationError("Nonce already used")

    async def _verify_signature(self, partner_id: UUID, signature: str, request_body: bytes):
        """HMAC 서명 검증"""
        if not signature:
            raise AuthenticationError("Missing X-Signature header")

        secret = await self._get_partner_secret(partner_id)
        if not secret:
            logger.error(f"Shared secret not found for partner: {partner_id}")
            raise AuthenticationError("Invalid partner configuration")

        computed_hash = hmac.new(secret.encode('utf-8'), request_body, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed_hash, signature):
            logger.warning(f"Invalid signature for partner {partner_id}. Expected: {computed_hash}, Got: {signature}")
            raise AuthenticationError("Invalid signature")

    async def process_callback(
        self, request: Request, partner_id: UUID
    ) -> Dict[str, Any]:
        """
        게임 콜백 처리 (보안 강화 버전)
        
        Args:
            request: FastAPI Request 객체
            partner_id: 파트너 ID (API 키 인증 등을 통해 얻음)
            
        Returns:
            Dict[str, Any]: 응답 데이터
            
        Raises:
            HTTPException: 유효성 검증 실패 또는 처리 오류 시
        """
        try:
            # 0. 요청 본문 읽기 (서명 검증에 필요)
            request_body = await request.body()
            try:
                data = await request.json() # JSON 파싱 시도
            except json.JSONDecodeError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

            # 1. 형식 검증 (필수 필드) - Pydantic 모델 사용 권장
            required_fields = ["token", "action", "round_id", "reference_id", "timestamp", "nonce"]
            for field in required_fields:
                if field not in data:
                    raise ValidationError(f"Missing required field: {field}")

            # 2. 타임스탬프 검증
            timestamp = data.get("timestamp")
            if not isinstance(timestamp, int):
                raise ValidationError("Invalid timestamp format")
            await self._verify_timestamp(timestamp)

            # 3. 논스(Nonce) 검증
            nonce = data.get("nonce")
            if not isinstance(nonce, str) or not nonce:
                raise ValidationError("Invalid nonce format")
            await self._verify_nonce(nonce)

            # 4. 서명 검증
            signature = request.headers.get("X-Signature")
            if not signature:
                raise AuthenticationError("Missing X-Signature header") # 명시적 에러 발생
            await self._verify_signature(partner_id, signature, request_body)

            # 5. 세션 토큰 검증
            session = await self.game_repo.get_active_session_by_token(data["token"])
            if not session:
                # 세션 파트너 ID와 요청 파트너 ID 일치 여부도 확인하는 것이 좋음
                # if session.partner_id != partner_id: ...
                logger.warning(f"Invalid or expired session token used: {data['token']}")
                raise AuthenticationError("Invalid or expired session token") # 인증 에러로 변경

            # --- 모든 검증 통과 ---

            # 6. 트랜잭션 중복 확인 (기존 로직)
            existing_tx = await self.game_repo.get_game_transaction_by_reference(data["reference_id"])
            if existing_tx:
                # 멱등성 처리: 성공적으로 완료된 트랜잭션이면 이전 결과 반환
                if existing_tx.status == "completed":
                    # 지갑 잔액은 최신 상태로 다시 조회하는 것이 안전할 수 있음
                    current_wallet = await self.wallet_repo.get_wallet_by_player_id(session.player_id, partner_id, existing_tx.currency)
                    balance = current_wallet.balance if current_wallet else existing_tx.session.wallet.balance # 안전하게 조회

                    logger.info(f"Idempotent callback processed for reference_id: {data['reference_id']}")
                    return {
                        "status": "success",
                        "balance": str(balance),
                        "currency": existing_tx.currency,
                        "transaction_id": str(existing_tx.id) # 고유 ID 반환
                    }
                # 실패했거나 처리 중인 트랜잭션이면 오류 반환 또는 재시도 로직 (상황에 따라 다름)
                else:
                    logger.warning(f"Callback attempt for non-completed transaction reference_id: {data['reference_id']} with status {existing_tx.status}")
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Transaction {data['reference_id']} is already being processed or failed."
                    )

            # 7. 행동 유형에 따른 처리 (기존 로직)
            action = data["action"]
            if action == "bet":
                return await self._process_bet_callback(data, session, partner_id)
            elif action == "win":
                return await self._process_win_callback(data, session, partner_id)
            elif action == "refund":
                return await self._process_refund_callback(data, session, partner_id)
            else:
                raise ValidationError(f"Unsupported action: {action}")

        except ValidationError as e:
            logger.warning(f"Callback validation failed: {str(e)}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        except AuthenticationError as e:
            logger.warning(f"Callback authentication failed: {str(e)}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
        except HTTPException as e:
            # 이미 HTTPException인 경우 그대로 전달
            raise e
        except Exception as e:
            # 예상치 못한 내부 오류
            logger.exception(f"Unexpected error processing callback for partner {partner_id}") # 스택 트레이스 로깅
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error during callback processing")
    
    async def _process_bet_callback(
        self, data: Dict[str, Any], session: GameSession, partner_id: UUID
    ) -> Dict[str, Any]:
        """
        베팅 콜백 처리
        
        Args:
            data: 콜백 데이터
            session: 게임 세션
            partner_id: 파트너 ID
            
        Returns:
            Dict[str, Any]: 응답 데이터
        """
        # 금액 검증
        if "amount" not in data or float(data["amount"]) <= 0:
            raise ValidationError("Invalid bet amount")
        
        # 베팅 요청 생성
        bet_request = DebitRequest(
            player_id=session.player_id,
            reference_id=data["reference_id"],
            amount=float(data["amount"]),
            currency=session.session_data.get("currency"),
            game_id=session.game_id,
            game_session_id=session.id,
            metadata={
                "round_id": data["round_id"],
                "action": "bet",
                "game_data": data.get("game_data", {})
            }
        )
        
        # 지갑 서비스를 통한 베팅 처리
        try:
            response = await self.wallet_service.debit(bet_request, partner_id)
            
            # 게임 트랜잭션 생성
            await self._create_game_transaction(
                session.id, 
                response.reference_id,
                data["round_id"],
                "bet",
                response.amount,
                response.currency,
                "completed",
                data.get("provider_transaction_id"),
                data.get("game_data", {})
            )
            
            return {
                "status": "success",
                "balance": str(response.balance),
                "currency": response.currency,
                "transaction_id": response.reference_id
            }
        except Exception as e:
            logger.error(f"Failed to process bet: {str(e)}")
            
            # 게임 트랜잭션 (실패) 생성
            await self._create_game_transaction(
                session.id, 
                data["reference_id"],
                data["round_id"],
                "bet",
                float(data["amount"]),
                session.session_data.get("currency"),
                "failed",
                data.get("provider_transaction_id"),
                data.get("game_data", {})
            )
            
            return {
                "status": "error",
                "code": "INSUFFICIENT_FUNDS" if "insufficient" in str(e).lower() else "INTERNAL_ERROR",
                "message": str(e)
            }
    
    async def _process_win_callback(
        self, data: Dict[str, Any], session: GameSession, partner_id: UUID
    ) -> Dict[str, Any]:
        """
        승리 콜백 처리
        
        Args:
            data: 콜백 데이터
            session: 게임 세션
            partner_id: 파트너 ID
            
        Returns:
            Dict[str, Any]: 응답 데이터
        """
        # 금액 검증
        if "amount" not in data or float(data["amount"]) <= 0:
            raise ValidationError("Invalid win amount")
        
        # 승리 요청 생성
        win_request = CreditRequest(
            player_id=session.player_id,
            reference_id=data["reference_id"],
            amount=float(data["amount"]),
            currency=session.session_data.get("currency"),
            game_id=session.game_id,
            game_session_id=session.id,
            metadata={
                "round_id": data["round_id"],
                "action": "win",
                "game_data": data.get("game_data", {})
            }
        )
        
        # 지갑 서비스를 통한 승리 처리
        try:
            response = await self.wallet_service.credit(win_request, partner_id)
            
            # 게임 트랜잭션 생성
            await self._create_game_transaction(
                session.id, 
                response.reference_id,
                data["round_id"],
                "win",
                response.amount,
                response.currency,
                "completed",
                data.get("provider_transaction_id"),
                data.get("game_data", {})
            )
            
            return {
                "status": "success",
                "balance": str(response.balance),
                "currency": response.currency,
                "transaction_id": response.reference_id
            }
        except Exception as e:
            logger.error(f"Failed to process win: {str(e)}")
            
            # 게임 트랜잭션 (실패) 생성
            await self._create_game_transaction(
                session.id, 
                data["reference_id"],
                data["round_id"],
                "win",
                float(data["amount"]),
                session.session_data.get("currency"),
                "failed",
                data.get("provider_transaction_id"),
                data.get("game_data", {})
            )
            
            return {
                "status": "error",
                "code": "INTERNAL_ERROR",
                "message": str(e)
            }
    
    async def _process_refund_callback(
        self, data: Dict[str, Any], session: GameSession, partner_id: UUID
    ) -> Dict[str, Any]:
        """
        환불 콜백 처리
        
        Args:
            data: 콜백 데이터
            session: 게임 세션
            partner_id: 파트너 ID
            
        Returns:
            Dict[str, Any]: 응답 데이터
        """
        # 롤백 대상 트랜잭션 확인
        if "original_reference_id" not in data:
            raise ValidationError("Missing original_reference_id for refund")
        
        # 롤백 요청 생성
        rollback_request = RollbackRequest(
            player_id=session.player_id,
            reference_id=data["reference_id"],
            original_reference_id=data["original_reference_id"]
        )
        
        # 지갑 서비스를 통한 롤백 처리
        try:
            response = await self.wallet_service.rollback(rollback_request, partner_id)
            
            # 게임 트랜잭션 생성
            await self._create_game_transaction(
                session.id, 
                response.reference_id,
                data["round_id"],
                "refund",
                response.amount,
                response.currency,
                "completed",
                data.get("provider_transaction_id"),
                {
                    "original_reference_id": data["original_reference_id"],
                    "game_data": data.get("game_data", {})
                }
            )
            
            return {
                "status": "success",
                "balance": str(response.balance),
                "currency": response.currency,
                "transaction_id": response.reference_id
            }
        except Exception as e:
            logger.error(f"Failed to process refund: {str(e)}")
            
            # 게임 트랜잭션 (실패) 생성
            await self._create_game_transaction(
                session.id, 
                data["reference_id"],
                data["round_id"],
                "refund",
                0.0,  # 금액은 알 수 없음
                session.session_data.get("currency"),
                "failed",
                data.get("provider_transaction_id"),
                {
                    "original_reference_id": data["original_reference_id"],
                    "error": str(e),
                    "game_data": data.get("game_data", {})
                }
            )
            
            return {
                "status": "error",
                "code": "TRANSACTION_ERROR",
                "message": str(e)
            }
    
    async def _create_game_transaction(
        self,
        session_id: UUID,
        reference_id: str,
        round_id: str,
        action: str,
        amount: float,
        currency: str,
        status: str,
        provider_transaction_id: Optional[str] = None,
        game_data: Optional[Dict[str, Any]] = None
    ) -> GameTransaction:
        """
        게임 트랜잭션 생성
        
        Args:
            session_id: 세션 ID
            reference_id: 참조 ID
            round_id: 라운드 ID
            action: 액션 (bet, win, refund)
            amount: 금액
            currency: 통화
            status: 상태
            provider_transaction_id: 제공자 트랜잭션 ID
            game_data: 게임 데이터
            
        Returns:
            GameTransaction: 생성된 게임 트랜잭션
        """
        tx = GameTransaction(
            id=uuid4(),
            session_id=session_id,
            reference_id=reference_id,
            round_id=round_id,
            action=action,
            amount=amount,
            currency=currency,
            status=status,
            provider_transaction_id=provider_transaction_id,
            game_data=game_data or {}
        )
        
        return await self.game_repo.create_game_transaction(tx)

    # --- BaseService Abstract Method Implementations --- 

    async def _find_one(self, query: Dict[str, Any]) -> Optional[Game]:
        """ID 또는 다른 고유 식별자로 게임 조회 (레포지토리 사용)"""
        if len(query) == 1 and self.id_field in query:
            return await self.game_repo.get_game_by_id(query[self.id_field])
        # Add other find conditions if needed and supported by repo, e.g.:
        # elif 'game_code' in query and 'provider_code' in query:
        #     return await self.game_repo.get_game_by_code(query['game_code'], query['provider_code'])
        logger.debug(f"_find_one called with unhandled query in GameService: {query}")
        return None

    async def _find_many(
        self, skip: int, limit: int, 
        filters: Optional[Dict[str, Any]], 
        sort_by: Optional[str], sort_order: str
    ) -> Tuple[List[Game], int]:
        """게임 목록 및 총 개수 조회 (레포지토리의 list_games 직접 사용)"""
        # GameRepository.list_games가 필터, 정렬, 페이지네이션 및 총 개수 반환을 모두 처리
        try:
             entities, total = await self.game_repo.list_games(
                 offset=skip, 
                 limit=limit,
                 filters=filters, # Pass filters directly
                 sort_by=sort_by, # Pass sort_by directly
                 sort_order=sort_order # Pass sort_order directly
             )
             return entities, total
        except Exception as e:
            # Handle potential repository errors
            logger.error(f"Error calling game_repo.list_games: {e}", exc_info=True)
            # Re-raise as a DatabaseError or let BaseService handle
            raise DatabaseError("Failed to list games due to repository error.") from e

    async def _create_entity(self, data: Dict[str, Any]) -> Game:
        """새 게임 생성 (레포지토리 사용)"""
        # _validate_create_data hook can be added for checks like provider existence
        # Ensure provider_id exists if it's part of 'data'
        provider_id = data.get('provider_id')
        if provider_id:
             provider = await self.get_provider(provider_id)
             if not provider:
                 raise ValidationError(f"Provider with id {provider_id} not found.")
             # You might want to add provider status checks here too
             # if provider.status != 'active': raise ServiceUnavailableException(...)
             
        new_game = self.model_class(**data)
        try:
             return await self.game_repo.create_game(new_game)
        except IntegrityError as e: # Catch potential unique constraint errors from repo
             await self.db.rollback()
             logger.warning(f"Conflict creating game, possibly duplicate external_id/provider: {e}")
             # Example: Check for specific constraint name if needed
             raise ConflictError("Game with the same external ID for this provider might already exist.") from e
        except Exception as e:
             await self.db.rollback()
             raise DatabaseError("Failed to create game entity.") from e

    async def _update_entity(self, entity: Game, data: Dict[str, Any]) -> Game:
        """게임 정보 업데이트 (레포지토리 사용)"""
        # _validate_update_data hook can be added for complex checks
        
        # Apply updates to the entity object
        for key, value in data.items():
            setattr(entity, key, value)
            
        # The repository update method handles the flush/refresh
        try:
             # Assuming repo.update_game modifies the passed entity and flushes
             updated_entity = await self.game_repo.update_game(entity)
             return updated_entity
        except IntegrityError as e: # Catch potential unique constraint errors
             await self.db.rollback()
             logger.warning(f"Conflict updating game {entity.id}, possibly duplicate external_id/provider: {e}")
             raise ConflictError("Game update resulted in a conflict (e.g., duplicate external ID).") from e
        except Exception as e:
             await self.db.rollback()
             raise DatabaseError(f"Failed to update game entity {entity.id}.") from e

    async def _delete_entity(self, entity: Game) -> bool:
        """게임 삭제 (물리적 삭제, 레포지토리 사용)"""
        # Assuming hard delete based on GameRepository.delete_game signature
        try:
             success = await self.game_repo.delete_game(entity.id)
             # repo.delete_game returns bool
             return success
        except Exception as e:
            await self.db.rollback()
            raise DatabaseError(f"Failed to delete game entity {entity.id}.") from e