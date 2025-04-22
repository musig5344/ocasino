"""
보고서 및 정산 서비스
파트너 보고서, 트랜잭션 내역, 정산 등 비즈니스 로직 담당
"""
import logging
from uuid import UUID, uuid4
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, date, timedelta
from decimal import Decimal
import json
import csv
import io

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, and_, or_, desc, select, case
from fastapi import HTTPException, status

from backend.models.domain.wallet import Transaction, Balance
from backend.models.domain.game import Game, GameSession, GameTransaction
from backend.models.domain.partner import Partner
from backend.repositories.wallet_repository import WalletRepository
from backend.repositories.game_repository import GameRepository
from backend.repositories.partner_repository import PartnerRepository

logger = logging.getLogger(__name__)

class ReportingService:
    """보고서 및 정산 서비스"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.wallet_repo = WalletRepository(db)
        self.game_repo = GameRepository(db)
        self.partner_repo = PartnerRepository(db)
    
    async def get_daily_summary(
        self, partner_id: UUID, date_value: date, currency: str
    ) -> Dict[str, Any]:
        """
        일일 거래 요약 조회
        
        Args:
            partner_id: 파트너 ID
            date_value: 날짜
            currency: 통화
            
        Returns:
            Dict[str, Any]: 일일 요약
        """
        # 일일 요약 조회
        summary = await self.wallet_repo.get_daily_summary(partner_id, date_value, currency)
        
        # 순 게임 수익 계산 (GGR: Gross Gaming Revenue)
        bet_total = summary["bet_total"]
        win_total = summary["win_total"]
        ggr = bet_total - win_total
        
        # 순 입출금 계산
        deposit_total = summary["deposit_total"]
        withdrawal_total = summary["withdrawal_total"]
        net_deposit = deposit_total - withdrawal_total
        
        # 결과 구성
        result = {
            "date": date_value.isoformat(),
            "partner_id": str(partner_id),
            "currency": currency,
            "transactions": {
                "deposit": {
                    "count": await self._get_transaction_count(partner_id, date_value, "deposit", currency),
                    "amount": float(deposit_total)
                },
                "withdrawal": {
                    "count": await self._get_transaction_count(partner_id, date_value, "withdrawal", currency),
                    "amount": float(withdrawal_total)
                },
                "bet": {
                    "count": await self._get_transaction_count(partner_id, date_value, "bet", currency),
                    "amount": float(bet_total)
                },
                "win": {
                    "count": await self._get_transaction_count(partner_id, date_value, "win", currency),
                    "amount": float(win_total)
                }
            },
            "metrics": {
                "net_deposit": float(net_deposit),
                "ggr": float(ggr),
                "commission": float(summary["commission_total"]),
                "unique_players": await self._get_unique_players(partner_id, date_value)
            }
        }
        
        return result
    
    async def _get_transaction_count(
        self, partner_id: UUID, date_value: date, tx_type: str, currency: str
    ) -> int:
        """
        거래 건수 조회
        
        Args:
            partner_id: 파트너 ID
            date_value: 날짜
            tx_type: 거래 유형
            currency: 통화
            
        Returns:
            int: 거래 건수
        """
        start_datetime = datetime.combine(date_value, datetime.min.time())
        end_datetime = datetime.combine(date_value, datetime.max.time())
        
        count = await self.db.execute(
            self.db.query(func.count(Transaction.id)).filter(
                Transaction.partner_id == partner_id,
                Transaction.transaction_type == tx_type,
                Transaction.currency == currency,
                Transaction.created_at.between(start_datetime, end_datetime),
                Transaction.status == "completed"
            )
        )
        
        return count.scalar() or 0
    
    async def _get_unique_players(self, partner_id: UUID, date_value: date) -> int:
        """
        일일 고유 플레이어 수 조회
        
        Args:
            partner_id: 파트너 ID
            date_value: 날짜
            
        Returns:
            int: 고유 플레이어 수
        """
        start_datetime = datetime.combine(date_value, datetime.min.time())
        end_datetime = datetime.combine(date_value, datetime.max.time())
        
        count = await self.db.execute(
            self.db.query(func.count(func.distinct(Transaction.player_id))).filter(
                Transaction.partner_id == partner_id,
                Transaction.created_at.between(start_datetime, end_datetime),
                Transaction.status == "completed"
            )
        )
        
        return count.scalar() or 0
    
    async def get_monthly_summary(
        self, partner_id: UUID, year: int, month: int, currency: str
    ) -> Dict[str, Any]:
        """
        월간 거래 요약 조회
        
        Args:
            partner_id: 파트너 ID
            year: 연도
            month: 월
            currency: 통화
            
        Returns:
            Dict[str, Any]: 월간 요약
        """
        # 월의 첫날과 마지막 날 계산
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        # 일별 요약 수집
        current_date = start_date
        daily_summaries = []
        
        while current_date <= end_date:
            daily_summary = await self.get_daily_summary(partner_id, current_date, currency)
            daily_summaries.append(daily_summary)
            current_date += timedelta(days=1)
        
        # 합계 계산
        deposit_amount = sum(summary["transactions"]["deposit"]["amount"] for summary in daily_summaries)
        withdrawal_amount = sum(summary["transactions"]["withdrawal"]["amount"] for summary in daily_summaries)
        bet_amount = sum(summary["transactions"]["bet"]["amount"] for summary in daily_summaries)
        win_amount = sum(summary["transactions"]["win"]["amount"] for summary in daily_summaries)
        commission_amount = sum(summary["metrics"]["commission"] for summary in daily_summaries)
        
        # 월간 지표 계산
        net_deposit = deposit_amount - withdrawal_amount
        ggr = bet_amount - win_amount
        
        # 결과 구성
        result = {
            "year": year,
            "month": month,
            "partner_id": str(partner_id),
            "currency": currency,
            "totals": {
                "deposit": deposit_amount,
                "withdrawal": withdrawal_amount,
                "bet": bet_amount,
                "win": win_amount,
                "commission": commission_amount
            },
            "metrics": {
                "net_deposit": net_deposit,
                "ggr": ggr,
                "active_days": len([s for s in daily_summaries if any(s["transactions"][t]["count"] > 0 for t in ["deposit", "withdrawal", "bet", "win"])]),
                "unique_players": await self._get_monthly_unique_players(partner_id, start_date, end_date)
            },
            "daily_summaries": daily_summaries
        }
        
        return result
    
    async def _get_monthly_unique_players(
        self, partner_id: UUID, start_date: date, end_date: date
    ) -> int:
        """
        월간 고유 플레이어 수 조회
        
        Args:
            partner_id: 파트너 ID
            start_date: 시작 날짜
            end_date: 종료 날짜
            
        Returns:
            int: 고유 플레이어 수
        """
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.max.time())
        
        count = await self.db.execute(
            self.db.query(func.count(func.distinct(Transaction.player_id))).filter(
                Transaction.partner_id == partner_id,
                Transaction.created_at.between(start_datetime, end_datetime),
                Transaction.status == "completed"
            )
        )
        
        return count.scalar() or 0
    
    async def get_game_performance(
        self, partner_id: UUID, start_date: date, end_date: date, 
        currency: str, game_id: Optional[UUID] = None, 
        provider_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        게임 성능 보고서 조회
        
        Args:
            partner_id: 파트너 ID
            start_date: 시작 날짜
            end_date: 종료 날짜
            currency: 통화
            game_id: 게임 ID 필터 (선택)
            provider_id: 게임 제공자 ID 필터 (선택)
            
        Returns:
            Dict[str, Any]: 게임 성능 보고서
        """
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.max.time())
        
        # 쿼리 구성
        query = self.db.query(
            Game.id,
            Game.name,
            Game.game_code,
            Game.category,
            Game.provider_id,
            GameProvider.name.label("provider_name"),
            func.count(GameSession.id).label("session_count"),
            func.count(func.distinct(GameSession.player_id)).label("unique_players"),
            func.sum(case((GameTransaction.action == "bet", GameTransaction.amount), else_=0)).label("bet_amount"),
            func.sum(case((GameTransaction.action == "win", GameTransaction.amount), else_=0)).label("win_amount")
        ).join(
            GameProvider, Game.provider_id == GameProvider.id
        ).outerjoin(
            GameSession, Game.id == GameSession.game_id
        ).outerjoin(
            GameTransaction, GameSession.id == GameTransaction.session_id
        ).filter(
            GameSession.partner_id == partner_id,
            GameSession.created_at.between(start_datetime, end_datetime),
            GameTransaction.currency == currency
        ).group_by(
            Game.id, Game.name, Game.game_code, Game.category, Game.provider_id, GameProvider.name
        )
        
        # 필터 적용
        if game_id:
            query = query.filter(Game.id == game_id)
        if provider_id:
            query = query.filter(Game.provider_id == provider_id)
        
        # 쿼리 실행
        result = await query.all()
        
        # 결과 변환
        games = []
        for row in result:
            bet_amount = float(row.bet_amount or 0)
            win_amount = float(row.win_amount or 0)
            ggr = bet_amount - win_amount
            
            games.append({
                "game_id": str(row.id),
                "name": row.name,
                "game_code": row.game_code,
                "category": row.category,
                "provider": {
                    "id": str(row.provider_id),
                    "name": row.provider_name
                },
                "metrics": {
                    "session_count": row.session_count,
                    "unique_players": row.unique_players,
                    "bet_amount": bet_amount,
                    "win_amount": win_amount,
                    "ggr": ggr,
                    "hold_percentage": (ggr / bet_amount * 100) if bet_amount > 0 else 0
                }
            })
        
        return {
            "partner_id": str(partner_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "currency": currency,
            "games": games
        }
    
    async def get_player_activity(
        self, partner_id: UUID, player_id: UUID, 
        start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        플레이어 활동 보고서 조회
        
        Args:
            partner_id: 파트너 ID
            player_id: 플레이어 ID
            start_date: 시작 날짜 (선택)
            end_date: 종료 날짜 (선택)
            
        Returns:
            Dict[str, Any]: 플레이어 활동 보고서
        """
        # 기본 날짜 범위: 최근 30일
        if not end_date:
            end_date = date.today()
        if not start_date:
            start_date = end_date - timedelta(days=30)
        
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.max.time())
        
        # 지갑 정보 조회
        wallet = await self.wallet_repo.get_player_wallet(player_id, partner_id)
        
        if not wallet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Wallet not found for player {player_id}"
            )
        
        # 트랜잭션 통계 조회
        tx_stats = await self.db.execute(
            self.db.query(
                Transaction.transaction_type,
                func.count(Transaction.id).label("count"),
                func.sum(Transaction.amount).label("amount")
            ).filter(
                Transaction.player_id == player_id,
                Transaction.partner_id == partner_id,
                Transaction.created_at.between(start_datetime, end_datetime),
                Transaction.status == "completed"
            ).group_by(
                Transaction.transaction_type
            )
        )
        
        tx_results = tx_stats.all()
        
        # 통계 구성
        transactions = {
            "deposit": {"count": 0, "amount": 0},
            "withdrawal": {"count": 0, "amount": 0},
            "bet": {"count": 0, "amount": 0},
            "win": {"count": 0, "amount": 0}
        }
        
        for row in tx_results:
            tx_type = row.transaction_type
            if tx_type in transactions:
                transactions[tx_type] = {
                    "count": row.count,
                    "amount": float(row.amount or 0)
                }
        
        # 게임 활동 조회
        game_stats = await self.db.execute(
            self.db.query(
                Game.id,
                Game.name,
                func.count(GameSession.id).label("session_count"),
                func.sum(case((GameTransaction.action == "bet", GameTransaction.amount), else_=0)).label("bet_amount"),
                func.sum(case((GameTransaction.action == "win", GameTransaction.amount), else_=0)).label("win_amount")
            ).join(
                GameSession, Game.id == GameSession.game_id
            ).outerjoin(
                GameTransaction, GameSession.id == GameTransaction.session_id
            ).filter(
                GameSession.player_id == player_id,
                GameSession.partner_id == partner_id,
                GameSession.created_at.between(start_datetime, end_datetime)
            ).group_by(
                Game.id, Game.name
            )
        )
        
        game_results = game_stats.all()
        
        # 게임 활동 구성
        games = []
        for row in game_results:
            bet_amount = float(row.bet_amount or 0)
            win_amount = float(row.win_amount or 0)
            
            games.append({
                "game_id": str(row.id),
                "name": row.name,
                "session_count": row.session_count,
                "bet_amount": bet_amount,
                "win_amount": win_amount,
                "net_win": win_amount - bet_amount
            })
        
        # 로그인 통계 조회
        login_stats = await self.db.execute(
            self.db.query(
                func.count(GameSession.id).label("login_count"),
                func.min(GameSession.created_at).label("first_login"),
                func.max(GameSession.created_at).label("last_login")
            ).filter(
                GameSession.player_id == player_id,
                GameSession.partner_id == partner_id,
                GameSession.created_at.between(start_datetime, end_datetime)
            )
        )
        
        login_result = login_stats.first()
        
        # 결과 구성
        result = {
            "player_id": str(player_id),
            "partner_id": str(partner_id),
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            },
            "wallet": {
                "id": str(wallet.id),
                "currency": wallet.currency,
                "current_balance": float(wallet.balance)
            },
            "transactions": transactions,
            "metrics": {
                "net_deposit": transactions["deposit"]["amount"] - transactions["withdrawal"]["amount"],
                "net_win": transactions["win"]["amount"] - transactions["bet"]["amount"],
                "login_count": login_result.login_count if login_result else 0,
                "first_login": login_result.first_login.isoformat() if login_result and login_result.first_login else None,
                "last_login": login_result.last_login.isoformat() if login_result and login_result.last_login else None
            },
            "games": games
        }
        
        return result
    
    async def generate_report_csv(
        self, partner_id: UUID, report_type: str, 
        start_date: date, end_date: date, 
        currency: str = None, filters: Dict[str, Any] = None
    ) -> Tuple[str, str]:
        """
        CSV 보고서 생성
        
        Args:
            partner_id: 파트너 ID
            report_type: 보고서 유형 ("transactions", "game_performance", "daily_summary", "monthly_summary")
            start_date: 시작 날짜
            end_date: 종료 날짜
            currency: 통화 (선택)
            filters: 추가 필터 (선택)
            
        Returns:
            Tuple[str, str]: (CSV 파일명, CSV 내용)
        """
        # 파트너 확인
        partner = await self.partner_repo.get_partner_by_id(partner_id)
        if not partner:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Partner {partner_id} not found"
            )
        
        # 보고서 유형에 따라 데이터 생성
        if report_type == "transactions":
            data = await self._generate_transaction_report(partner_id, start_date, end_date, currency, filters)
            headers = ["Transaction ID", "Date", "Type", "Player ID", "Amount", "Currency", "Status"]
        elif report_type == "game_performance":
            data = await self._generate_game_performance_report(partner_id, start_date, end_date, currency, filters)
            headers = ["Game ID", "Game Name", "Provider", "Category", "Sessions", "Players", "Bet Amount", "Win Amount", "GGR", "Hold %"]
        elif report_type == "daily_summary":
            data = await self._generate_daily_summary_report(partner_id, start_date, end_date, currency)
            headers = ["Date", "Deposits", "Withdrawals", "Bets", "Wins", "GGR", "Net Deposit", "Unique Players"]
        elif report_type == "monthly_summary":
            data = await self._generate_monthly_summary_report(partner_id, start_date, end_date, currency)
            headers = ["Year", "Month", "Deposits", "Withdrawals", "Bets", "Wins", "GGR", "Net Deposit", "Unique Players", "Commission"]
        else:
            raise ValueError(f"Unsupported report type: {report_type}")
        
        # CSV 생성
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        
        # 헤더 추가
        writer.writerow(headers)
        
        # 데이터 추가
        for row in data:
            writer.writerow(row)
        
        # 파일명 생성
        filename = f"{partner.code}_{report_type}_{start_date.isoformat()}_{end_date.isoformat()}.csv"
        
        return filename, buffer.getvalue()
    
    async def _generate_transaction_report(
        self, partner_id: UUID, start_date: date, end_date: date, 
        currency: str = None, filters: Dict[str, Any] = None
    ) -> List[List[Any]]:
        """
        트랜잭션 보고서 데이터 생성
        
        Args:
            partner_id: 파트너 ID
            start_date: 시작 날짜
            end_date: 종료 날짜
            currency: 통화 (선택)
            filters: 추가 필터 (선택)
            
        Returns:
            List[List[Any]]: 보고서 행 목록
        """
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.max.time())
        
        # 쿼리 구성
        query = self.db.query(
            Transaction.id,
            Transaction.created_at,
            Transaction.transaction_type,
            Transaction.player_id,
            Transaction.amount,
            Transaction.currency,
            Transaction.status
        ).filter(
            Transaction.partner_id == partner_id,
            Transaction.created_at.between(start_datetime, end_datetime)
        )
        
        # 필터 적용
        if currency:
            query = query.filter(Transaction.currency == currency)
        
        if filters:
            if 'player_id' in filters:
                query = query.filter(Transaction.player_id == filters['player_id'])
            if 'transaction_type' in filters:
                query = query.filter(Transaction.transaction_type == filters['transaction_type'])
            if 'status' in filters:
                query = query.filter(Transaction.status == filters['status'])
        
        # 쿼리 실행
        result = await query.all()
        
        # 결과 변환
        data = []
        for row in result:
            data.append([
                str(row.id),
                row.created_at.isoformat(),
                row.transaction_type,
                str(row.player_id),
                float(row.amount),
                row.currency,
                row.status
            ])
        
        return data
    
    async def _generate_game_performance_report(
        self, partner_id: UUID, start_date: date, end_date: date, 
        currency: str = None, filters: Dict[str, Any] = None
    ) -> List[List[Any]]:
        """
        게임 성능 보고서 데이터 생성
        
        Args:
            partner_id: 파트너 ID
            start_date: 시작 날짜
            end_date: 종료 날짜
            currency: 통화 (선택)
            filters: 추가 필터 (선택)
            
        Returns:
            List[List[Any]]: 보고서 행 목록
        """
        # 게임 성능 보고서 조회
        report = await self.get_game_performance(
            partner_id, start_date, end_date, 
            currency or "USD", 
            game_id=filters.get('game_id') if filters else None,
            provider_id=filters.get('provider_id') if filters else None
        )
        
        # 결과 변환
        data = []
        for game in report["games"]:
            metrics = game["metrics"]
            hold_percentage = metrics["hold_percentage"]
            
            data.append([
                game["game_id"],
                game["name"],
                game["provider"]["name"],
                game["category"],
                metrics["session_count"],
                metrics["unique_players"],
                metrics["bet_amount"],
                metrics["win_amount"],
                metrics["ggr"],
                f"{hold_percentage:.2f}%"
            ])
        
        return data
    
    async def _generate_daily_summary_report(
        self, partner_id: UUID, start_date: date, end_date: date, currency: str = None
    ) -> List[List[Any]]:
        """
        일별 요약 보고서 데이터 생성
        
        Args:
            partner_id: 파트너 ID
            start_date: 시작 날짜
            end_date: 종료 날짜
            currency: 통화 (선택)
            
        Returns:
            List[List[Any]]: 보고서 행 목록
        """
        currency = currency or "USD"
        
        # 날짜 범위 내 모든 날짜 생성
        current_date = start_date
        data = []
        
        while current_date <= end_date:
            # 일일 요약 조회
            summary = await self.get_daily_summary(partner_id, current_date, currency)
            
            # 필요한 데이터 추출
            transactions = summary["transactions"]
            metrics = summary["metrics"]
            
            data.append([
                current_date.isoformat(),
                transactions["deposit"]["amount"],
                transactions["withdrawal"]["amount"],
                transactions["bet"]["amount"],
                transactions["win"]["amount"],
                metrics["ggr"],
                metrics["net_deposit"],
                metrics["unique_players"]
            ])
            
            # 다음 날짜로 이동
            current_date += timedelta(days=1)
        
        return data
    
    async def _generate_monthly_summary_report(
        self, partner_id: UUID, start_date: date, end_date: date, currency: str = None
    ) -> List[List[Any]]:
        """
        월별 요약 보고서 데이터 생성
        
        Args:
            partner_id: 파트너 ID
            start_date: 시작 날짜
            end_date: 종료 날짜
            currency: 통화 (선택)
            
        Returns:
            List[List[Any]]: 보고서 행 목록
        """
        currency = currency or "USD"
        
        # 시작 및 종료 월 계산
        start_year, start_month = start_date.year, start_date.month
        end_year, end_month = end_date.year, end_date.month
        
        data = []
        current_year, current_month = start_year, start_month
        
        while (current_year < end_year) or (current_year == end_year and current_month <= end_month):
            # 월간 요약 조회
            summary = await self.get_monthly_summary(partner_id, current_year, current_month, currency)
            
            # 필요한 데이터 추출
            totals = summary["totals"]
            metrics = summary["metrics"]
            
            data.append([
                current_year,
                current_month,
                totals["deposit"],
                totals["withdrawal"],
                totals["bet"],
                totals["win"],
                metrics["ggr"],
                metrics["net_deposit"],
                metrics["unique_players"],
                totals["commission"]
            ])
            
            # 다음 월로 이동
            if current_month == 12:
                current_year += 1
                current_month = 1
            else:
                current_month += 1
        
        return data