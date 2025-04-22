"""
게임 서비스
게임 통합, 세션 관리, 게임 트랜잭션 처리 등 비즈니스 로직 담당
"""
import logging
from uuid import UUID, uuid4
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import secrets
import hmac
import hashlib
import json
import httpx
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from backend.models.domain.game import Game, GameProvider, GameSession, GameTransaction
from backend.repositories.game_repository import GameRepository
from backend.repositories.wallet_repository import WalletRepository
from backend.services.wallet.wallet_service import WalletService
from backend.schemas.game import GameLaunchRequest, GameLaunchResponse
from backend.schemas.wallet import DebitRequest, CreditRequest, RollbackRequest
from backend.core.config import settings
from backend.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

class GameService:
    """게임 서비스"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.game_repo = GameRepository(db)
        self.wallet_repo = WalletRepository(db)
        self.wallet_service = WalletService(db)
    
    async def get_game(self, game_id: UUID) -> Optional[Game]:
        """
        ID로 게임 조회
        
        Args:
            game_id: 게임 ID
            
        Returns:
            Optional[Game]: 게임 객체 또는 None
        """
        return await self.game_repo.get_game_by_id(game_id)
    
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
        game = await self.game_repo.get_game_by_id(request.game_id)
        if not game:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Game {request.game_id} not found"
            )
        
        # 게임 제공자 조회
        provider = await self.game_repo.get_provider_by_id(game.provider_id)
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
        token = self._generate_session_token()
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
    
    async def process_callback(
        self, data: Dict[str, Any], partner_id: UUID
    ) -> Dict[str, Any]:
        """
        게임 콜백 처리
        
        Args:
            data: 콜백 데이터
            partner_id: 파트너 ID
            
        Returns:
            Dict[str, Any]: 응답 데이터
            
        Raises:
            ValidationError: 유효성 검증 실패 시
        """
        # 기본 유효성 검증
        required_fields = ["token", "action", "round_id", "reference_id"]
        for field in required_fields:
            if field not in data:
                raise ValidationError(f"Missing required field: {field}")
        
        # 세션 토큰 검증
        session = await self.game_repo.get_active_session_by_token(data["token"])
        if not session:
            raise ValidationError(f"Invalid or expired session token: {data['token']}")
        
        # 트랜잭션 중복 확인
        existing_tx = await self.game_repo.get_game_transaction_by_reference(data["reference_id"])
        if existing_tx:
            # 동일 트랜잭션 재시도 (멱등성)
            return {
                "status": "success",
                "balance": str(existing_tx.session.wallet.balance),
                "currency": existing_tx.currency,
                "transaction_id": str(existing_tx.id)
            }
        
        # 행동 유형에 따른 처리
        if data["action"] == "bet":
            return await self._process_bet_callback(data, session, partner_id)
        elif data["action"] == "win":
            return await self._process_win_callback(data, session, partner_id)
        elif data["action"] == "refund":
            return await self._process_refund_callback(data, session, partner_id)
        else:
            raise ValidationError(f"Unsupported action: {data['action']}")
    
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