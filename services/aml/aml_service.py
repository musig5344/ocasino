"""
자금세탁방지(AML) 서비스
트랜잭션 모니터링, 위험 평가, 보고 등 AML 관련 비즈니스 로직 담당
"""
import logging
from uuid import UUID, uuid4
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func

from backend.models.domain.wallet import Transaction
from backend.models.domain.aml import AMLAlert, AMLRiskProfile, AMLReport
from backend.repositories.wallet_repository import WalletRepository

logger = logging.getLogger(__name__)

class AMLService:
    """자금세탁방지(AML) 서비스"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.wallet_repo = WalletRepository(db)
        
        # 위험 경계값 설정
        self.thresholds = {
            "USD": 10000.0,  # 미국 달러
            "EUR": 9500.0,   # 유로
            "GBP": 8000.0,   # 영국 파운드
            "KRW": 12000000.0,  # 한국 원
            "JPY": 1300000.0,  # 일본 엔
            "default": 10000.0  # 기본값 (USD 기준)
        }
        
        # 고위험 국가 목록
        self.high_risk_countries = [
            "AF", "BY", "BI", "CF", "CD", "KP", "ER", "IR", "IQ", "LY", 
            "ML", "MM", "NI", "PK", "RU", "SO", "SS", "SD", "SY", "VE", 
            "YE", "ZW"
        ]
    
    async def analyze_transaction(self, transaction_id: UUID) -> Dict[str, Any]:
        """
        트랜잭션 AML 분석
        
        Args:
            transaction_id: 트랜잭션 ID
            
        Returns:
            Dict[str, Any]: 분석 결과
        """
        # 트랜잭션 조회
        transaction = await self.wallet_repo.get_transaction(transaction_id)
        if not transaction:
            logger.error(f"Transaction not found: {transaction_id}")
            return {"error": "Transaction not found"}
        
        # 이미 분석된 트랜잭션인지 확인
        existing_analysis = await self._get_existing_analysis(transaction_id)
        if existing_analysis:
            return existing_analysis
        
        # 플레이어 위험 프로필 조회 또는 생성
        risk_profile = await self._get_or_create_risk_profile(transaction.player_id)
        
        # 분석 수행
        analysis_result = await self._perform_analysis(transaction, risk_profile)
        
        # 알림 생성 (필요한 경우)
        if analysis_result["requires_alert"]:
            await self._create_alert(transaction, analysis_result)
        
        # 위험 프로필 업데이트
        await self._update_risk_profile(risk_profile, transaction, analysis_result)
        
        # 분석 결과 저장
        await self._save_analysis_result(transaction_id, analysis_result)
        
        return analysis_result
    
    async def _get_existing_analysis(self, transaction_id: UUID) -> Optional[Dict[str, Any]]:
        """
        기존 분석 결과 조회
        
        Args:
            transaction_id: 트랜잭션 ID
            
        Returns:
            Optional[Dict[str, Any]]: 분석 결과 또는 None
        """
        # 실제 구현에서는 DB에서 분석 결과 조회
        # 여기서는 간단히 None 반환 (항상 새로 분석)
        return None
    
    async def _get_or_create_risk_profile(self, player_id: UUID) -> AMLRiskProfile:
        """
        플레이어 위험 프로필 조회 또는 생성
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            AMLRiskProfile: 위험 프로필
        """
        # 위험 프로필 조회
        # 실제 구현에서는 DB에서 조회 후 없으면 생성
        risk_profile = AMLRiskProfile(
            player_id=player_id,
            overall_risk_score=50.0,  # 기본 중간 위험
            deposit_count_30d=0,
            deposit_amount_30d=0.0,
            withdrawal_count_30d=0,
            withdrawal_amount_30d=0.0,
            wager_to_deposit_ratio=0.0,
            risk_factors={},
            created_at=datetime.utcnow(),
            last_assessment_at=datetime.utcnow()
        )
        
        # 트랜잭션 통계 계산
        await self._calculate_transaction_stats(risk_profile)
        
        return risk_profile
    
    async def _calculate_transaction_stats(self, risk_profile: AMLRiskProfile) -> None:
        """
        위험 프로필 트랜잭션 통계 계산
        
        Args:
            risk_profile: 위험 프로필
        """
        # 30일 기간 설정
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        
        # 입금 통계
        deposit_stats = await self.db.execute(
            self.db.query(
                func.count(Transaction.id).label('count'),
                func.sum(Transaction.amount).label('amount')
            ).filter(
                Transaction.player_id == risk_profile.player_id,
                Transaction.transaction_type == "deposit",
                Transaction.created_at.between(start_date, end_date),
                Transaction.status == "completed"
            )
        )
        deposit_result = deposit_stats.first()
        
        if deposit_result:
            risk_profile.deposit_count_30d = deposit_result.count or 0
            risk_profile.deposit_amount_30d = float(deposit_result.amount or 0)
        
        # 출금 통계
        withdrawal_stats = await self.db.execute(
            self.db.query(
                func.count(Transaction.id).label('count'),
                func.sum(Transaction.amount).label('amount')
            ).filter(
                Transaction.player_id == risk_profile.player_id,
                Transaction.transaction_type == "withdrawal",
                Transaction.created_at.between(start_date, end_date),
                Transaction.status == "completed"
            )
        )
        withdrawal_result = withdrawal_stats.first()
        
        if withdrawal_result:
            risk_profile.withdrawal_count_30d = withdrawal_result.count or 0
            risk_profile.withdrawal_amount_30d = float(withdrawal_result.amount or 0)
        
        # 베팅 통계
        bet_stats = await self.db.execute(
            self.db.query(
                func.sum(Transaction.amount).label('amount')
            ).filter(
                Transaction.player_id == risk_profile.player_id,
                Transaction.transaction_type == "bet",
                Transaction.created_at.between(start_date, end_date),
                Transaction.status == "completed"
            )
        )
        bet_result = bet_stats.first()
        
        bet_amount = float(bet_result.amount or 0) if bet_result else 0
        
        # 베팅 대 입금 비율 계산
        if risk_profile.deposit_amount_30d > 0:
            risk_profile.wager_to_deposit_ratio = bet_amount / risk_profile.deposit_amount_30d
        else:
            risk_profile.wager_to_deposit_ratio = 0
    
    async def _perform_analysis(
        self, transaction: Transaction, risk_profile: AMLRiskProfile
    ) -> Dict[str, Any]:
        """
        트랜잭션 상세 분석 수행
        
        Args:
            transaction: 트랜잭션 객체
            risk_profile: 위험 프로필
            
        Returns:
            Dict[str, Any]: 분석 결과
        """
        # 기본 분석 결과 초기화
        result = {
            "transaction_id": str(transaction.id),
            "player_id": str(transaction.player_id),
            "transaction_type": transaction.transaction_type,
            "amount": float(transaction.amount),
            "currency": transaction.currency,
            "risk_score": 0,
            "risk_factors": {},
            "requires_alert": False,
            "requires_report": False,
            "alert_type": None,
            "created_at": datetime.utcnow().isoformat()
        }
        
        # 통화별 임계값 가져오기
        threshold = self.thresholds.get(transaction.currency, self.thresholds["default"])
        result["threshold"] = threshold
        
        # 위험 요소 분석
        risk_factors = {}
        
        # 1. 대규모 거래 확인
        if float(transaction.amount) >= threshold:
            risk_factors["large_transaction"] = {
                "amount": float(transaction.amount),
                "threshold": threshold,
                "score": 70
            }
            result["risk_score"] += 70
        
        # 2. 구조화 의심 확인 (임계값 바로 아래 금액의 반복 거래)
        if await self._check_structuring(transaction, threshold):
            risk_factors["structuring"] = {
                "description": "Multiple transactions just below threshold",
                "score": 80
            }
            result["risk_score"] += 80
        
        # 3. 비정상적인 행동 패턴 확인
        if risk_profile.wager_to_deposit_ratio < 0.3 and risk_profile.deposit_amount_30d > threshold:
            risk_factors["low_wagering"] = {
                "ratio": risk_profile.wager_to_deposit_ratio,
                "deposit_amount": risk_profile.deposit_amount_30d,
                "score": 60
            }
            result["risk_score"] += 60
        
        # 4. 고위험 국가 확인
        player_country = transaction.metadata.get("country") if transaction.metadata else None
        if player_country and player_country.upper() in self.high_risk_countries:
            risk_factors["high_risk_country"] = {
                "country": player_country,
                "score": 50
            }
            result["risk_score"] += 50
        
        # 위험 점수 조정 (최대 100)
        result["risk_score"] = min(100, result["risk_score"])
        
        # 위험 요소 저장
        result["risk_factors"] = risk_factors
        
        # 알림/보고 필요 여부 결정
        result["requires_alert"] = result["risk_score"] >= 60
        result["requires_report"] = result["risk_score"] >= 80 or "large_transaction" in risk_factors
        
        # 알림 유형 결정
        if result["requires_alert"]:
            if "large_transaction" in risk_factors:
                result["alert_type"] = "large_transaction"
            elif "structuring" in risk_factors:
                result["alert_type"] = "structuring"
            elif "low_wagering" in risk_factors:
                result["alert_type"] = "unusual_pattern"
            elif "high_risk_country" in risk_factors:
                result["alert_type"] = "high_risk_country"
            else:
                result["alert_type"] = "suspicious_activity"
        
        return result
    
    async def _check_structuring(self, transaction: Transaction, threshold: float) -> bool:
        """
        구조화 의심 확인 (임계값 회피 목적의 분할 거래)
        
        Args:
            transaction: 트랜잭션 객체
            threshold: 통화별 임계값
            
        Returns:
            bool: 구조화 의심 여부
        """
        # 24시간 내 동일 유형 트랜잭션 확인
        start_time = transaction.created_at - timedelta(hours=24)
        
        transactions = await self.wallet_repo.get_player_transactions(
            transaction.player_id,
            transaction.partner_id,
            transaction.transaction_type,
            start_time,
            transaction.created_at
        )
        
        # 자신을 제외한 트랜잭션만 필터링
        transactions = [tx for tx in transactions if tx.id != transaction.id]
        
        if not transactions:
            return False
        
        # 임계값의 70-99% 사이 트랜잭션 수 확인
        threshold_lower = threshold * 0.7
        threshold_upper = threshold * 0.99
        
        suspicious_count = sum(
            1 for tx in transactions 
            if threshold_lower <= float(tx.amount) <= threshold_upper
        )
        
        # 현재 트랜잭션도 해당 범위인지 확인
        current_suspicious = threshold_lower <= float(transaction.amount) <= threshold_upper
        
        # 의심 기준: 24시간 내 임계값 바로 아래 금액의 트랜잭션이 3건 이상
        return (suspicious_count >= 2) or (suspicious_count >= 1 and current_suspicious)
    
    async def _create_alert(self, transaction: Transaction, analysis_result: Dict[str, Any]) -> None:
        """
        AML 알림 생성
        
        Args:
            transaction: 트랜잭션 객체
            analysis_result: 분석 결과
        """
        alert = AMLAlert(
            id=uuid4(),
            player_id=transaction.player_id,
            partner_id=transaction.partner_id,
            transaction_id=transaction.id,
            alert_type=analysis_result["alert_type"],
            risk_score=analysis_result["risk_score"],
            description=self._generate_alert_description(analysis_result),
            status="open",
            risk_factors=analysis_result["risk_factors"],
            data={
                "transaction_amount": float(transaction.amount),
                "transaction_currency": transaction.currency,
                "transaction_type": transaction.transaction_type,
                "threshold": analysis_result["threshold"]
            },
            created_at=datetime.utcnow()
        )
        
        self.db.add(alert)
        await self.db.flush()
        
        logger.info(f"Created AML alert: {alert.id} for transaction {transaction.id}")
    
    def _generate_alert_description(self, analysis_result: Dict[str, Any]) -> str:
        """
        알림 설명 생성
        
        Args:
            analysis_result: 분석 결과
            
        Returns:
            str: 알림 설명
        """
        alert_type = analysis_result["alert_type"]
        
        if alert_type == "large_transaction":
            return f"Large transaction of {analysis_result['amount']} {analysis_result['currency']} exceeded threshold of {analysis_result['threshold']}"
        elif alert_type == "structuring":
            return "Multiple transactions just below reporting threshold detected"
        elif alert_type == "unusual_pattern":
            return "Unusual pattern detected: low wagering compared to deposit amount"
        elif alert_type == "high_risk_country":
            country = analysis_result["risk_factors"]["high_risk_country"]["country"]
            return f"Transaction associated with high-risk country: {country}"
        else:
            return "Suspicious activity detected"
    
    async def _update_risk_profile(
        self, risk_profile: AMLRiskProfile, transaction: Transaction, analysis_result: Dict[str, Any]
    ) -> None:
        """
        위험 프로필 업데이트
        
        Args:
            risk_profile: 위험 프로필
            transaction: 트랜잭션 객체
            analysis_result: 분석 결과
        """
        # 거래 유형에 따라 프로필 업데이트
        if transaction.transaction_type == "deposit":
            risk_profile.deposit_count_30d += 1
            risk_profile.deposit_amount_30d += float(transaction.amount)
        elif transaction.transaction_type == "withdrawal":
            risk_profile.withdrawal_count_30d += 1
            risk_profile.withdrawal_amount_30d += float(transaction.amount)
        
        # 위험 점수 업데이트
        # 기존 점수와 새 분석 결과를 가중 평균
        old_weight = 0.7
        new_weight = 0.3
        risk_profile.overall_risk_score = (
            risk_profile.overall_risk_score * old_weight + 
            analysis_result["risk_score"] * new_weight
        )
        
        # 위험 요소 업데이트
        for factor_key, factor_data in analysis_result["risk_factors"].items():
            if factor_key not in risk_profile.risk_factors:
                risk_profile.risk_factors[factor_key] = {
                    "first_detected": datetime.utcnow().isoformat(),
                    "count": 1,
                    "last_detected": datetime.utcnow().isoformat(),
                    "details": factor_data
                }
            else:
                risk_profile.risk_factors[factor_key]["count"] += 1
                risk_profile.risk_factors[factor_key]["last_detected"] = datetime.utcnow().isoformat()
                risk_profile.risk_factors[factor_key]["details"] = factor_data
        
        # 평가 시간 업데이트
        risk_profile.last_assessment_at = datetime.utcnow()
        
        # DB 업데이트
        self.db.add(risk_profile)
        await self.db.flush()
    
    async def _save_analysis_result(self, transaction_id: UUID, analysis_result: Dict[str, Any]) -> None:
        """
        분석 결과 저장
        
        Args:
            transaction_id: 트랜잭션 ID
            analysis_result: 분석 결과
        """
        # 실제 구현에서는 DB에 분석 결과 저장
        # 여기서는 로그만 남김
        logger.info(f"Saved AML analysis for transaction {transaction_id}")
    
    async def get_alerts(
        self, 
        partner_id: Optional[UUID] = None,
        player_id: Optional[UUID] = None,
        status: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        offset: int = 0,
        limit: int = 100
    ) -> List[AMLAlert]:
        """
        AML 알림 목록 조회
        
        Args:
            partner_id: 파트너 ID 필터
            player_id: 플레이어 ID 필터
            status: 상태 필터
            start_date: 시작 날짜
            end_date: 종료 날짜
            offset: 페이징 오프셋
            limit: 페이징 제한
            
        Returns:
            List[AMLAlert]: 알림 목록
        """
        # 쿼리 구성
        query = self.db.query(AMLAlert)
        
        if partner_id:
            query = query.filter(AMLAlert.partner_id == partner_id)
        if player_id:
            query = query.filter(AMLAlert.player_id == player_id)
        if status:
            query = query.filter(AMLAlert.status == status)
        if start_date:
            query = query.filter(AMLAlert.created_at >= start_date)
        if end_date:
            query = query.filter(AMLAlert.created_at <= end_date)
        
        # 정렬 및 페이징
        query = query.order_by(AMLAlert.created_at.desc()).offset(offset).limit(limit)
        
        result = await query.all()
        return result
    
    async def update_alert_status(self, alert_id: UUID, status: str, notes: Optional[str] = None) -> AMLAlert:
        """
        알림 상태 업데이트
        
        Args:
            alert_id: 알림 ID
            status: 새 상태
            notes: 메모
            
        Returns:
            AMLAlert: 업데이트된 알림
        """
        # 알림 조회
        alert = await self.db.query(AMLAlert).filter(AMLAlert.id == alert_id).first()
        
        if not alert:
            logger.error(f"Alert not found: {alert_id}")
            raise ValueError(f"Alert {alert_id} not found")
        
        # 상태 업데이트
        alert.status = status
        
        if notes:
            alert.notes = notes
        
        alert.updated_at = datetime.utcnow()
        
        # "reported" 상태로 변경된 경우 보고서 생성
        if status == "reported" and alert.status != "reported":
            alert.reported_at = datetime.utcnow()
            await self._create_aml_report(alert)
        
        await self.db.flush()
        
        return alert
    
    async def _create_aml_report(self, alert: AMLAlert) -> AMLReport:
        """
        AML 보고서 생성
        
        Args:
            alert: 알림 객체
            
        Returns:
            AMLReport: 생성된 보고서
        """
        # 보고서 ID 생성
        report_id = f"REP-{uuid4().hex[:8].upper()}"
        
        # 보고서 생성
        report = AMLReport(
            id=uuid4(),
            report_id=report_id,
            alert_id=alert.id,
            player_id=alert.player_id,
            partner_id=alert.partner_id,
            transaction_id=alert.transaction_id,
            report_type="SAR",  # Suspicious Activity Report
            status="submitted",
            risk_score=alert.risk_score,
            report_data={
                "alert_type": alert.alert_type,
                "risk_factors": alert.risk_factors,
                "transaction_data": alert.data,
                "description": alert.description
            },
            notes=alert.notes,
            created_at=datetime.utcnow(),
            submitted_at=datetime.utcnow()
        )
        
        self.db.add(report)
        await self.db.flush()
        
        logger.info(f"Created AML report: {report.report_id} for alert {alert.id}")
        
        return report