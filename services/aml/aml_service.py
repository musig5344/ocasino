"""
자금세탁방지(AML) 서비스
트랜잭션 모니터링, 위험 평가, 보고 등 AML 관련 비즈니스 로직 담당
"""
import logging
from uuid import UUID, uuid4
from typing import Optional, Dict, Any, List, Tuple, Union
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, and_, or_, desc, select, case, text, insert
from sqlalchemy.orm import Session

from backend.models.domain.wallet import Transaction, TransactionType, TransactionStatus
from backend.models.aml import (
    AMLAlert, AMLRiskProfile, AMLReport, AMLTransaction,
    AlertType, AlertStatus, AlertSeverity, ReportType, ReportingJurisdiction
)
from backend.repositories.wallet_repository import WalletRepository
from backend.schemas.aml import AMLAlertCreate, AlertStatusUpdate

logger = logging.getLogger(__name__)

class AMLService:
    """자금세탁방지(AML) 서비스"""
    
    def __init__(self, db: Union[AsyncSession, Session]):
        self.db = db
        if hasattr(db, 'query'):
            # SQLAlchemy 동기 세션
            self.is_async = False
            self.wallet_repo = WalletRepository(db)
        else:
            # SQLAlchemy 비동기 세션
            self.is_async = True
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
    
    async def analyze_transaction(self, transaction_id: Union[UUID, str], user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        트랜잭션 AML 분석
        
        Args:
            transaction_id: 트랜잭션 ID
            user_id: 요청한 사용자 ID (선택사항)
            
        Returns:
            Dict[str, Any]: 분석 결과
        """
        # UUID 변환 (문자열로 입력받은 경우)
        if isinstance(transaction_id, str):
            try:
                transaction_id = UUID(transaction_id)
            except ValueError:
                logger.error(f"Invalid transaction ID format: {transaction_id}")
                return {"error": "Invalid transaction ID format"}
        
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
        risk_profile = await self._get_or_create_risk_profile(transaction.player_id, transaction.partner_id)
        
        # 분석 수행
        analysis_result = await self._perform_analysis(transaction, risk_profile)
        
        # 알림 생성 (필요한 경우)
        alert_id = None
        if analysis_result["requires_alert"]:
            alert = await self._create_alert(transaction, analysis_result)
            alert_id = alert.id
            analysis_result["alert"] = alert_id
        
        # 위험 프로필 업데이트
        await self._update_risk_profile(risk_profile, transaction, analysis_result)
        
        # 분석 결과 저장
        await self._save_analysis_result(transaction_id, analysis_result)
        
        # AML 트랜잭션 기록 저장
        aml_transaction = await self._save_aml_transaction(transaction, analysis_result)
        
        # 보고 필요 여부에 따라 보고서 생성
        if analysis_result["requires_report"]:
            report = await self._create_aml_report(
                alert_id=alert_id, 
                transaction=transaction, 
                analysis_result=analysis_result,
                created_by=user_id or "system"
            )
            analysis_result["report_id"] = report.report_id
        
        return analysis_result
    
    async def _get_existing_analysis(self, transaction_id: UUID) -> Optional[Dict[str, Any]]:
        """
        기존 분석 결과 조회
        
        Args:
            transaction_id: 트랜잭션 ID
            
        Returns:
            Optional[Dict[str, Any]]: 분석 결과 또는 None
        """
        try:
            if self.is_async:
                # 비동기 쿼리
                query = select(AMLTransaction).where(AMLTransaction.transaction_id == str(transaction_id))
                result = await self.db.execute(query)
                aml_transaction = result.scalars().first()
            else:
                # 동기 쿼리
                aml_transaction = self.db.query(AMLTransaction).filter(
                    AMLTransaction.transaction_id == str(transaction_id)
                ).first()
            
            if aml_transaction:
                # 기존 분석 결과가 있으면 반환
                return {
                    "transaction_id": aml_transaction.transaction_id,
                    "player_id": aml_transaction.player_id,
                    "risk_score": aml_transaction.risk_score,
                    "risk_factors": aml_transaction.risk_factors,
                    "is_large_transaction": aml_transaction.is_large_transaction,
                    "is_suspicious_pattern": aml_transaction.is_suspicious_pattern,
                    "is_unusual_for_player": aml_transaction.is_unusual_for_player,
                    "is_structuring_attempt": aml_transaction.is_structuring_attempt,
                    "is_regulatory_report_required": aml_transaction.is_regulatory_report_required,
                    "analysis_details": aml_transaction.analysis_details,
                    "created_at": aml_transaction.created_at.isoformat()
                }
            return None
        except Exception as e:
            logger.error(f"Error getting existing analysis: {str(e)}")
            return None
    
    async def _check_behavior_pattern_deviation(self, transaction: Transaction, risk_profile: AMLRiskProfile) -> Dict[str, Any]:
        """
        Comprehensive behavior pattern analysis comparing current transaction against
        player's established behavior patterns
        
        Args:
            transaction: Transaction to analyze
            risk_profile: Player's risk profile
            
        Returns:
            Dict[str, Any]: Analysis results with deviation details
        """
        result = {
            "deviation_detected": False,
            "severity": 0,
            "details": {}
        }
        
        # Need enough transaction history to establish patterns
        if risk_profile.transaction_count < 10:
            result["details"]["insufficient_history"] = True
            return result
        
        # Check time patterns (when player typically transacts)
        time_deviation = await self._check_time_pattern_deviation(transaction, risk_profile)
        
        # Check amount patterns (typical transaction amounts)
        amount_deviation = await self._check_amount_pattern_deviation(transaction, risk_profile)
        
        # Check frequency patterns (how often player transacts)
        frequency_deviation = await self._check_frequency_pattern_deviation(transaction, risk_profile)
        
        # Track which pattern types show deviations
        deviations_found = []
        
        if time_deviation["deviation_detected"]:
            deviations_found.append("time")
            result["details"]["time_deviation"] = time_deviation["details"]
        
        if amount_deviation["deviation_detected"]:
            deviations_found.append("amount")
            result["details"]["amount_deviation"] = amount_deviation["details"]
        
        if frequency_deviation["deviation_detected"]:
            deviations_found.append("frequency")
            result["details"]["frequency_deviation"] = frequency_deviation["details"]
        
        # Calculate overall deviation result
        result["deviation_detected"] = len(deviations_found) > 0
        
        # Calculate severity based on number of deviating patterns
        result["severity"] = min(1.0, len(deviations_found) / 3.0)
        
        # Include patterns analyzed and which showed deviations
        result["details"]["patterns_analyzed"] = ["time", "amount", "frequency"]
        result["details"]["deviations_found"] = deviations_found
        
        return result

    async def _check_time_pattern_deviation(self, transaction: Transaction, risk_profile: AMLRiskProfile) -> Dict[str, Any]:
        """
        Analyze if transaction timing deviates from player's normal patterns
        
        Args:
            transaction: Transaction to analyze
            risk_profile: Player's risk profile
            
        Returns:
            Dict[str, Any]: Time pattern analysis result
        """
        # Get player's transaction history for this type (last 30 days)
        start_time = transaction.created_at - timedelta(days=30)
        
        transactions = await self.wallet_repo.get_player_transactions(
            transaction.player_id,
            transaction.partner_id,
            transaction.transaction_type,
            start_time,
            transaction.created_at
        )
        
        # Not enough data to establish pattern
        if len(transactions) < 5:
            return {"deviation_detected": False, "details": {"insufficient_data": True}}
        
        # Analyze hour of day patterns
        hour_distribution = {}
        for tx in transactions:
            hour = tx.created_at.hour
            hour_distribution[hour] = hour_distribution.get(hour, 0) + 1
        
        # Determine player's normal hours (hours with at least 10% of activity)
        total_txs = len(transactions)
        normal_hours = [hour for hour, count in hour_distribution.items() 
                       if count >= max(1, total_txs * 0.1)]
        
        # Check if current transaction is outside normal hours
        current_hour = transaction.created_at.hour
        unusual_time = current_hour not in normal_hours
        
        # Also check day of week patterns
        day_distribution = {}
        for tx in transactions:
            day = tx.created_at.weekday()
            day_distribution[day] = day_distribution.get(day, 0) + 1
        
        # Determine normal days
        normal_days = [day for day, count in day_distribution.items() 
                       if count >= max(1, total_txs * 0.1)]
        
        current_day = transaction.created_at.weekday()
        unusual_day = current_day not in normal_days
        
        # Deviation detected if both time and day are unusual, or if time is highly unusual
        deviation_detected = (unusual_time and unusual_day) or (
            unusual_time and hour_distribution.get(current_hour, 0) == 0
        )
        
        return {
            "deviation_detected": deviation_detected,
            "details": {
                "current_hour": current_hour,
                "normal_hours": normal_hours,
                "unusual_time": unusual_time,
                "current_day": current_day,
                "normal_days": normal_days,
                "unusual_day": unusual_day,
                "hour_distribution": hour_distribution,
                "day_distribution": day_distribution
            }
        }

    async def _check_amount_pattern_deviation(self, transaction: Transaction, risk_profile: AMLRiskProfile) -> Dict[str, Any]:
        """
        Analyze if transaction amount deviates from player's normal patterns
        
        Args:
            transaction: Transaction to analyze
            risk_profile: Player's risk profile
            
        Returns:
            Dict[str, Any]: Amount pattern analysis result
        """
        # Get player's transaction history for this type (last 30 days)
        start_time = transaction.created_at - timedelta(days=30)
        
        transactions = await self.wallet_repo.get_player_transactions(
            transaction.player_id,
            transaction.partner_id,
            transaction.transaction_type,
            start_time,
            transaction.created_at
        )
        
        # Not enough data to establish pattern
        if len(transactions) < 5:
            return {"deviation_detected": False, "details": {"insufficient_data": True}}
        
        # Calculate amount statistics
        amounts = [float(tx.amount) for tx in transactions]
        avg_amount = sum(amounts) / len(amounts)
        
        # Calculate standard deviation
        variance = sum((amt - avg_amount) ** 2 for amt in amounts) / len(amounts)
        std_dev = variance ** 0.5 if variance > 0 else 0.01  # Avoid division by zero
        
        # Calculate z-score for current amount
        current_amount = float(transaction.amount)
        z_score = (current_amount - avg_amount) / std_dev
        
        # Create amount bins for distribution analysis
        min_amount = min(amounts)
        max_amount = max(amounts)
        bin_width = (max_amount - min_amount) / 5 if max_amount > min_amount else 1
        
        bins = {}
        for amt in amounts:
            bin_idx = min(4, int((amt - min_amount) / bin_width))
            bins[bin_idx] = bins.get(bin_idx, 0) + 1
        
        # Determine which bin current amount falls into
        if current_amount < min_amount:
            current_bin = "below_min"
        elif current_amount > max_amount:
            current_bin = "above_max"
        else:
            current_bin = int((current_amount - min_amount) / bin_width)
        
        # Deviation detected if z-score exceeds threshold or amount is outside historical range
        deviation_detected = (abs(z_score) > 2.5 or 
                             current_amount < min_amount or 
                             current_amount > max_amount)
        
        return {
            "deviation_detected": deviation_detected,
            "details": {
                "current_amount": current_amount,
                "avg_amount": avg_amount,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "std_deviation": std_dev,
                "z_score": z_score,
                "z_score_threshold": 2.5,
                "outside_range": current_amount < min_amount or current_amount > max_amount,
                "amount_distribution": bins,
                "current_bin": current_bin
            }
        }

    async def _check_frequency_pattern_deviation(self, transaction: Transaction, risk_profile: AMLRiskProfile) -> Dict[str, Any]:
        """
        Analyze if transaction frequency deviates from player's normal patterns
        
        Args:
            transaction: Transaction to analyze
            risk_profile: Player's risk profile
            
        Returns:
            Dict[str, Any]: Frequency pattern analysis result
        """
        # Calculate average transaction frequencies over different periods
        # Last 24 hours
        day_start = transaction.created_at - timedelta(days=1)
        day_txs = await self.wallet_repo.get_player_transactions(
            transaction.player_id,
            transaction.partner_id,
            transaction.transaction_type,
            day_start,
            transaction.created_at
        )
        
        # Last 7 days (excluding last 24 hours)
        week_start = transaction.created_at - timedelta(days=7)
        week_txs = await self.wallet_repo.get_player_transactions(
            transaction.player_id,
            transaction.partner_id,
            transaction.transaction_type,
            week_start,
            day_start
        )
        
        # Last 30 days (excluding last 7 days)
        month_start = transaction.created_at - timedelta(days=30)
        month_txs = await self.wallet_repo.get_player_transactions(
            transaction.player_id,
            transaction.partner_id,
            transaction.transaction_type,
            month_start,
            week_start
        )
        
        # Calculate frequencies
        day_count = len(day_txs)
        week_count = len(week_txs)
        month_count = len(month_txs)
        
        # Calculate average daily frequencies
        week_daily_avg = week_count / 6.0  # 7 days - 1 day
        month_daily_avg = month_count / 23.0  # 30 days - 7 days
        
        # Account for players with limited history
        if week_count == 0 and month_count == 0:
            return {"deviation_detected": False, "details": {"insufficient_data": True}}
        
        # Use maximum average as baseline (more conservative)
        baseline_daily_avg = max(week_daily_avg, month_daily_avg, 0.1)  # Minimum to avoid division by zero
        
        # Calculate frequency ratio
        frequency_ratio = day_count / baseline_daily_avg
        
        # Deviation detected if today's frequency is significantly higher
        deviation_detected = frequency_ratio > 3 and day_count > 3
        
        return {
            "deviation_detected": deviation_detected,
            "details": {
                "current_24h_count": day_count,
                "past_week_count": week_count,
                "past_month_count": month_count,
                "avg_daily_past_week": week_daily_avg,
                "avg_daily_past_month": month_daily_avg,
                "baseline_daily_avg": baseline_daily_avg,
                "frequency_ratio": frequency_ratio,
                "threshold_ratio": 3.0
            }
        }
    
    def _calculate_composite_risk(self, risk_factors: Dict[str, Any]) -> float:
        """
        Calculate additional risk based on combinations of risk factors that
        together represent higher risk than each factor individually
        
        Args:
            risk_factors: Dictionary of identified risk factors
            
        Returns:
            float: Additional risk score from combined factors
        """
        composite_score = 0
        
        # Define risk factor combinations with associated score increases
        high_risk_combinations = [
            # Structuring + rapid movement (coordinated fund movement)
            (["structuring", "rapid_movement"], 15),
            
            # Large transaction + unusual betting (potential layering)
            (["large_transaction", "unusual_betting"], 10),
            
            # Multi-account + any other factor (sophisticated operation)
            (["multi_account", "large_transaction"], 20),
            (["multi_account", "structuring"], 25),
            (["multi_account", "rapid_movement"], 20),
            (["multi_account", "unusual_betting"], 15),
            
            # High risk country + large transaction (regulatory risk)
            (["high_risk_country", "large_transaction"], 15),
            
            # Pattern deviation + suspicious activity (unusual behavior)
            (["pattern_deviation", "large_transaction"], 10),
            (["pattern_deviation", "structuring"], 15),
            (["pattern_deviation", "rapid_movement"], 15),
            (["pattern_deviation", "unusual_betting"], 12),
            
            # PEP match + any suspicious activity (regulatory & corruption risk)
            (["pep_match", "large_transaction"], 25),
            (["pep_match", "structuring"], 30),
            (["pep_match", "rapid_movement"], 20),
            (["pep_match", "unusual_betting"], 15),
            
            # Three or more factors together (sophisticated laundering)
            (["large_transaction", "unusual_betting", "rapid_movement"], 25),
            (["structuring", "unusual_betting", "high_risk_country"], 30)
        ]
        
        # Check each combination
        for factors, score in high_risk_combinations:
            if all(factor in risk_factors for factor in factors):
                composite_score += score
        
        # Cap the composite score
        return min(40, composite_score)

    def _determine_alert_type(self, risk_factors: Dict[str, Any]) -> AlertType:
        """
        Determine the most significant alert type for categorization
        
        Args:
            risk_factors: Dictionary of identified risk factors
            
        Returns:
            AlertType: Primary alert type to categorize the alert
        """
        # Priority order for alert types (highest priority first)
        priority_factors = [
            "pep_match",           # 정치적 노출 인물 (최우선 순위)
            "multi_account",        # Multi-account activity is highest priority
            "structuring",          # Structuring indicates intentional evasion
            "large_transaction",    # Large transactions have regulatory implications
            "rapid_movement",       # Quick fund movement
            "unusual_betting",      # Unusual betting patterns
            "high_risk_country",    # High-risk jurisdictions
            "pattern_deviation",    # Behavior pattern changes
            "low_wagering"          # Low wagering relative to deposits
        ]
        
        # Map to AlertType enum
        type_mapping = {
            "pep_match": AlertType.PEP_MATCH,
            "multi_account": AlertType.MULTI_ACCOUNT,
            "structuring": AlertType.STRUCTURING,
            "large_transaction": AlertType.LARGE_TRANSACTION,
            "rapid_movement": AlertType.RAPID_MOVEMENT,
            "unusual_betting": AlertType.UNUSUAL_BETTING,
            "high_risk_country": AlertType.HIGH_RISK_COUNTRY,
            "pattern_deviation": AlertType.PATTERN_DEVIATION,
            "low_wagering": AlertType.UNUSUAL_PATTERN
        }
        
        # Return highest priority factor present
        for factor in priority_factors:
            if factor in risk_factors:
                return type_mapping.get(factor, AlertType.UNUSUAL_PATTERN)
        
        # Default alert type if no specific factors identified
        return AlertType.UNUSUAL_PATTERN

    def _calculate_alert_priority(self, risk_score: float, risk_factors: Dict[str, Any]) -> AlertSeverity:
        """
        Calculate alert priority for triage and investigation workflow
        
        Args:
            risk_score: The calculated risk score
            risk_factors: Dictionary of identified risk factors
            
        Returns:
            AlertSeverity: Alert priority (high, medium, low)
        """
        # Critical priority criteria
        if risk_score >= 85 or "pep_match" in risk_factors:
            return AlertSeverity.CRITICAL
        
        # High priority criteria
        if risk_score >= 70:
            return AlertSeverity.HIGH
        
        # High priority for certain risk combinations
        high_priority_factors = ["multi_account", "structuring", "large_transaction"]
        if any(factor in risk_factors for factor in high_priority_factors) and risk_score >= 60:
            return AlertSeverity.HIGH
        
        # Medium priority for moderate risk scores
        if risk_score >= 40:
            return AlertSeverity.MEDIUM
        
        # Low priority for all others
        return AlertSeverity.LOW
    
    async def _create_alert(self, transaction: Transaction, analysis_result: Dict[str, Any]) -> AMLAlert:
        """
        Create a detailed AML alert with comprehensive analysis results
        
        Args:
            transaction: Transaction that triggered the alert
            analysis_result: Detailed risk analysis results
            
        Returns:
            AMLAlert: Created alert record
        """
        # 알림 유형과 우선순위 변환
        alert_type_str = analysis_result.get("alert_type", "unusual_pattern")
        alert_type = getattr(AlertType, alert_type_str.upper()) if hasattr(AlertType, alert_type_str.upper()) else AlertType.UNUSUAL_PATTERN
        
        priority_str = analysis_result.get("alert_priority", "medium")
        priority = getattr(AlertSeverity, priority_str.upper()) if hasattr(AlertSeverity, priority_str.upper()) else AlertSeverity.MEDIUM
        
        # Generate detailed alert description
        description = self._generate_alert_description(analysis_result)
        
        # Create alert record
        alert = AMLAlert(
            player_id=str(transaction.player_id),
            partner_id=str(transaction.partner_id) if transaction.partner_id else None,
            transaction_id=str(transaction.id),
            alert_type=alert_type,
            alert_severity=priority,
            alert_status=AlertStatus.NEW,
            description=description,
            detection_rule="automatic_detection",
            risk_score=analysis_result["risk_score"],
            transaction_ids=[str(transaction.id)],
            risk_factors=analysis_result["risk_factors"],
            transaction_details={
                "amount": float(transaction.amount),
                "currency": transaction.currency,
                "transaction_type": transaction.transaction_type,
                "created_at": transaction.created_at.isoformat(),
                "metadata": transaction.metadata
            },
            alert_data={
                "analysis_details": self._extract_analysis_highlights(analysis_result)
            },
            created_at=datetime.utcnow()
        )
        
        # Save alert to database
        self.db.add(alert)
        
        if self.is_async:
            await self.db.flush()
        else:
            self.db.flush()
        
        # Log alert creation
        logger.info(f"AML alert created: {alert.id} for transaction {transaction.id}, "
                  f"type: {alert_type}, priority: {priority}, score: {analysis_result['risk_score']}")
        
        # Send immediate notification for high priority alerts
        if priority in [AlertSeverity.HIGH, AlertSeverity.CRITICAL]:
            await self._send_alert_notification(alert)
        
        # Create regulatory report if required
        if analysis_result["requires_report"]:
            await self._create_aml_report(alert.id, transaction, analysis_result)
        
        return alert
    
    def _generate_alert_description(self, analysis_result: Dict[str, Any]) -> str:
        """
        Generate detailed human-readable alert description for investigators
        
        Args:
            analysis_result: Risk analysis results
            
        Returns:
            str: Formatted alert description
        """
        alert_type = analysis_result["alert_type"]
        risk_score = analysis_result["risk_score"]
        
        # Format risk factors for description
        risk_factors = list(analysis_result["risk_factors"].keys())
        risk_factors_str = ", ".join(factor.replace("_", " ").title() 
                                  for factor in risk_factors)
        
        # Base description
        base_desc = (f"{alert_type.replace('_', ' ').title()} detected with "
                   f"risk score {risk_score:.0f}/100")
        
        # Add specific details based on alert type
        if alert_type == "large_transaction":
            amount = analysis_result["amount"]
            currency = analysis_result["currency"]
            threshold = analysis_result["threshold"]
            detail = (f"Transaction of {amount} {currency} exceeded threshold "
                    f"of {threshold} {currency}")
        elif alert_type == "structuring":
            struct_details = analysis_result["risk_factors"]["structuring"].get("details", {})
            count = struct_details.get("total_suspicious_count", 0)
            detail = (f"Pattern of {count} transactions just below reporting threshold "
                    f"detected within 48 hours")
        elif alert_type == "rapid_movement":
            rm_details = analysis_result["risk_factors"]["rapid_movement"].get("details", {})
            ratio = rm_details.get("withdrawal_to_deposit_ratio", 0) * 100
            detail = (f"Withdrawal of {ratio:.0f}% of recent deposits within 24 hours "
                    f"of deposit")
        elif alert_type == "unusual_betting":
            bet_details = analysis_result["risk_factors"]["unusual_betting"].get("details", {})
            unusual = bet_details.get("unusual_factors", {})
            if unusual.get("statistical_outlier"):
                detail = "Betting amount statistically inconsistent with player's history"
            elif unusual.get("sudden_increase"):
                detail = "Sudden significant increase in betting amount"
            elif unusual.get("unusual_game"):
                detail = "Betting on games rarely played by this player"
            else:
                detail = "Unusual betting pattern detected"
        elif alert_type == "multi_account":
            ma_details = analysis_result["risk_factors"]["multi_account"].get("details", {})
            count = ma_details.get("linked_account_count", 0)
            detail = f"Activity linked to {count} other accounts sharing identifiers"
        elif alert_type == "high_risk_country":
            country = analysis_result["risk_factors"]["high_risk_country"].get("country", "unknown")
            detail = f"Transaction associated with high-risk country: {country}"
        elif alert_type == "pattern_deviation":
            pd_details = analysis_result["risk_factors"]["pattern_deviation"].get("details", {})
            deviations = pd_details.get("deviations_found", [])
            deviation_str = ", ".join(deviations)
            detail = f"Significant deviation from established patterns in: {deviation_str}"
        elif alert_type == "pep_match":
            detail = "Transaction involves a Politically Exposed Person requiring enhanced due diligence"
        else:
            detail = "Suspicious activity detected requiring investigation"
        
        # Combine all elements
        return f"{base_desc}. {detail}. Risk factors include: {risk_factors_str}."
    
    def _extract_analysis_highlights(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract key highlights from analysis for alert notification
        
        Args:
            analysis_result: Risk analysis results
            
        Returns:
            Dict[str, Any]: Highlighted analysis details
        """
        highlights = {
            "risk_score": analysis_result["risk_score"],
            "alert_type": analysis_result["alert_type"],
            "risk_factors": list(analysis_result["risk_factors"].keys()),
        }
        
        # Add relevant data based on which risk factors were identified
        for factor, data in analysis_result["risk_factors"].items():
            if factor == "large_transaction":
                highlights["transaction_to_threshold_ratio"] = (
                    analysis_result["amount"] / analysis_result["threshold"]
                )
            elif factor == "structuring":
                if "details" in data:
                    highlights["structuring"] = {
                        "transactions_in_range": len(data["details"].get("previous_transactions", [])),
                        "pattern_period_hours": 48
                    }
            elif factor == "rapid_movement":
                if "details" in data:
                    details = data["details"]
                    highlights["rapid_movement"] = {
                        "withdrawal_to_deposit_ratio": details.get("withdrawal_to_deposit_ratio"),
                        "hours_since_first_deposit": details.get("hours_since_first_deposit")
                    }
            elif factor == "multi_account":
                if "details" in data:
                    highlights["multi_account"] = {
                        "linked_account_count": data["details"].get("linked_account_count"),
                        "shared_identifiers": list(data["details"].get("identifiers", {}).keys())
                    }
            elif factor == "pattern_deviation":
                if "details" in data:
                    highlights["pattern_deviation"] = {
                        "deviations_found": data["details"].get("deviations_found", []),
                        "severity": data.get("severity", 0)
                    }
        
        return highlights
    
    async def _send_alert_notification(self, alert: AMLAlert) -> None:
        """
        Send notification for high-priority alerts to compliance team
        
        Args:
            alert: The AML alert to notify about
        """
        # Log the notification
        logger.warning(
            f"HIGH PRIORITY AML ALERT: {alert.id} - {alert.alert_type} - "
            f"Player: {alert.player_id} - Score: {alert.risk_score}"
        )
        
        # In a real implementation, this would call a notification service:
        # - Email/SMS to compliance team
        # - Create ticket in case management system
        # - Update compliance dashboard
        
        # await self.notification_service.send_compliance_alert({
        #     "alert_id": str(alert.id),
        #     "alert_type": alert.alert_type,
        #     "priority": "high",
        #     "player_id": str(alert.player_id),
        #     "partner_id": str(alert.partner_id),
        #     "transaction_id": str(alert.transaction_id),
        #     "risk_score": alert.risk_score,
        #     "description": alert.description,
        #     "timestamp": datetime.utcnow().isoformat()
        # })
    
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
        if transaction.transaction_type == TransactionType.DEPOSIT:
            risk_profile.deposit_count_30d += 1
            risk_profile.deposit_amount_30d += float(transaction.amount)
            risk_profile.deposit_count_7d += 1
            risk_profile.deposit_amount_7d += float(transaction.amount)
            risk_profile.last_deposit_at = transaction.created_at
        elif transaction.transaction_type == TransactionType.WITHDRAWAL:
            risk_profile.withdrawal_count_30d += 1
            risk_profile.withdrawal_amount_30d += float(transaction.amount)
            risk_profile.withdrawal_count_7d += 1
            risk_profile.withdrawal_amount_7d += float(transaction.amount)
            risk_profile.last_withdrawal_at = transaction.created_at
        elif transaction.transaction_type == TransactionType.BET:
            risk_profile.last_played_at = transaction.created_at
        
        # 위험 점수 업데이트
        # 기존 점수와 새 분석 결과를 가중 평균
        old_weight = 0.7
        new_weight = 0.3
        risk_profile.overall_risk_score = (
            risk_profile.overall_risk_score * old_weight + 
            analysis_result["risk_score"] * new_weight
        )
        
        # 특정 트랜잭션 유형에 대한 위험 점수 업데이트
        if transaction.transaction_type == TransactionType.DEPOSIT:
            risk_profile.deposit_risk_score = (
                risk_profile.deposit_risk_score * old_weight + 
                analysis_result["risk_score"] * new_weight
            )
        elif transaction.transaction_type == TransactionType.WITHDRAWAL:
            risk_profile.withdrawal_risk_score = (
                risk_profile.withdrawal_risk_score * old_weight + 
                analysis_result["risk_score"] * new_weight
            )
        elif transaction.transaction_type in [TransactionType.BET, TransactionType.WIN]:
            risk_profile.gameplay_risk_score = (
                risk_profile.gameplay_risk_score * old_weight + 
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
        
        # 베팅 대 입금 비율 재계산
        if risk_profile.deposit_amount_30d > 0:
            risk_profile.wager_to_deposit_ratio = (
                risk_profile.gameplay_risk_score * 100 / risk_profile.deposit_amount_30d
            )
        
        # 출금 대 입금 비율 재계산
        if risk_profile.deposit_amount_30d > 0:
            risk_profile.withdrawal_to_deposit_ratio = (
                risk_profile.withdrawal_amount_30d / risk_profile.deposit_amount_30d
            )
        
        # 평가 시간 업데이트
        risk_profile.last_assessment_at = datetime.utcnow()
        
        # DB 업데이트
        self.db.add(risk_profile)
        
        if self.is_async:
            await self.db.flush()
        else:
            self.db.flush()
    
    async def _save_analysis_result(self, transaction_id: UUID, analysis_result: Dict[str, Any]) -> None:
        """
        분석 결과 저장
        
        Args:
            transaction_id: 트랜잭션 ID
            analysis_result: 분석 결과
        """
        # 분석 결과 로깅
        logger.info(f"Saved AML analysis for transaction {transaction_id}")
        
        # 실제로는 여기서 저장하는 로직이 필요할 수 있음
        # 하지만 분석 결과는 이미 AMLTransaction에 저장되므로 추가 작업 필요 없음
    
    async def _save_aml_transaction(self, transaction: Transaction, analysis_result: Dict[str, Any]) -> AMLTransaction:
        """
        AML 트랜잭션 레코드 저장
        
        Args:
            transaction: 트랜잭션 객체
            analysis_result: 분석 결과
            
        Returns:
            AMLTransaction: 저장된 AML 트랜잭션 객체
        """
        # AML 트랜잭션 생성
        aml_transaction = AMLTransaction(
            transaction_id=str(transaction.id),
            player_id=str(transaction.player_id),
            partner_id=str(transaction.partner_id) if transaction.partner_id else None,
            currency=transaction.currency,
            amount=float(transaction.amount),
            transaction_type=transaction.transaction_type,
            is_large_transaction=analysis_result.get("is_large_transaction", False),
            is_suspicious_pattern=analysis_result.get("is_suspicious_pattern", False),
            is_unusual_for_player=analysis_result.get("is_unusual_for_player", False),
            is_structuring_attempt=analysis_result.get("is_structuring_attempt", False),
            is_regulatory_report_required=analysis_result.get("requires_report", False),
            risk_score=analysis_result["risk_score"],
            risk_factors=analysis_result["risk_factors"],
            regulatory_threshold_currency=transaction.currency,
            regulatory_threshold_amount=analysis_result.get("threshold", 0),
            analysis_version="1.0.0",
            analysis_details={
                "alert_id": analysis_result.get("alert"),
                "alert_type": analysis_result.get("alert_type"),
                "alert_priority": analysis_result.get("alert_priority"),
                "is_politically_exposed_person": analysis_result.get("is_politically_exposed_person", False),
                "is_high_risk_jurisdiction": analysis_result.get("is_high_risk_jurisdiction", False)
            }
        )
        
        # DB에 저장
        self.db.add(aml_transaction)
        
        if self.is_async:
            await self.db.flush()
        else:
            self.db.flush()
        
        logger.info(f"Saved AML transaction record for transaction {transaction.id}")
        
        return aml_transaction
    
    async def _create_aml_report(
        self, 
        alert_id: Optional[int] = None, 
        transaction: Optional[Transaction] = None, 
        analysis_result: Optional[Dict[str, Any]] = None,
        created_by: str = "system"
    ) -> AMLReport:
        """
        AML 보고서 생성
        
        Args:
            alert_id: 알림 ID (선택사항)
            transaction: 트랜잭션 객체 (선택사항)
            analysis_result: 분석 결과 (선택사항)
            created_by: 보고서 생성자
            
        Returns:
            AMLReport: 생성된 보고서
        """
        # 보고서 ID 생성
        report_id = f"REP-{uuid4().hex[:8].upper()}"
        
        # 내용 준비
        if alert_id is not None:
            # 알림에서 생성
            if self.is_async:
                query = select(AMLAlert).where(AMLAlert.id == alert_id)
                result = await self.db.execute(query)
                alert = result.scalars().first()
            else:
                alert = self.db.query(AMLAlert).filter(AMLAlert.id == alert_id).first()
            
            if not alert:
                logger.error(f"Alert not found for report creation: {alert_id}")
                raise ValueError(f"Alert {alert_id} not found")
            
            player_id = alert.player_id
            partner_id = alert.partner_id
            transaction_id = alert.transaction_id
            risk_score = alert.risk_score
            report_data = {
                "alert_type": str(alert.alert_type),
                "risk_factors": alert.risk_factors,
                "transaction_details": alert.transaction_details,
                "description": alert.description
            }
            
        elif transaction is not None and analysis_result is not None:
            # 트랜잭션과 분석 결과에서 직접 생성
            player_id = str(transaction.player_id)
            partner_id = str(transaction.partner_id) if transaction.partner_id else None
            transaction_id = str(transaction.id)
            risk_score = analysis_result["risk_score"]
            report_data = {
                "transaction_details": {
                    "id": str(transaction.id),
                    "amount": float(transaction.amount),
                    "currency": transaction.currency,
                    "transaction_type": transaction.transaction_type,
                    "created_at": transaction.created_at.isoformat()
                },
                "risk_factors": analysis_result["risk_factors"],
                "alert_type": analysis_result.get("alert_type"),
                "description": self._generate_alert_description(analysis_result)
            }
        else:
            logger.error("Insufficient data for report creation")
            raise ValueError("Either alert_id or (transaction and analysis_result) must be provided")
        
        # 보고서 유형 결정
        report_type = ReportType.SAR  # 기본값: Suspicious Activity Report
        
        # 규제 관할권 결정 (추후 확장 가능)
        jurisdiction = ReportingJurisdiction.MALTA  # 기본값
        
        # 거래 ID 배열 구성
        transaction_ids = [transaction_id] if transaction_id else []
        
        # 보고서 생성
        report = AMLReport(
            report_id=report_id,
            player_id=player_id,
            partner_id=partner_id,
            report_type=report_type,
            jurisdiction=jurisdiction,
            alert_id=alert_id,
            transaction_id=transaction_id,
            transaction_ids=transaction_ids,
            report_data=report_data,
            risk_score=risk_score,
            status="draft",
            created_by=created_by,
            created_at=datetime.utcnow()
        )
        
        self.db.add(report)
        
        if self.is_async:
            await self.db.flush()
        else:
            self.db.flush()
        
        logger.info(f"Created AML report: {report.report_id}")
        
        return report
    
    # API 서비스 메서드 추가
    async def get_alerts(
        self, 
        partner_id: Optional[str] = None,
        player_id: Optional[str] = None,
        status: Optional[AlertStatus] = None,
        severity: Optional[AlertSeverity] = None,
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
            severity: 중요도 필터
            start_date: 시작 날짜
            end_date: 종료 날짜
            offset: 페이징 오프셋
            limit: 페이징 제한
            
        Returns:
            List[AMLAlert]: 알림 목록
        """
        try:
            if self.is_async:
                # 비동기 쿼리 구성
                query = select(AMLAlert)
                
                if partner_id:
                    query = query.where(AMLAlert.partner_id == partner_id)
                if player_id:
                    query = query.where(AMLAlert.player_id == player_id)
                if status:
                    query = query.where(AMLAlert.alert_status == status)
                if severity:
                    query = query.where(AMLAlert.alert_severity == severity)
                if start_date:
                    query = query.where(AMLAlert.created_at >= start_date)
                if end_date:
                    query = query.where(AMLAlert.created_at <= end_date)
                
                # 정렬 및 페이징
                query = query.order_by(desc(AMLAlert.created_at)).offset(offset).limit(limit)
                
                result = await self.db.execute(query)
                alerts = result.scalars().all()
            else:
                # 동기 쿼리 구성
                query = self.db.query(AMLAlert)
                
                if partner_id:
                    query = query.filter(AMLAlert.partner_id == partner_id)
                if player_id:
                    query = query.filter(AMLAlert.player_id == player_id)
                if status:
                    query = query.filter(AMLAlert.alert_status == status)
                if severity:
                    query = query.filter(AMLAlert.alert_severity == severity)
                if start_date:
                    query = query.filter(AMLAlert.created_at >= start_date)
                if end_date:
                    query = query.filter(AMLAlert.created_at <= end_date)
                
                # 정렬 및 페이징
                alerts = query.order_by(desc(AMLAlert.created_at)).offset(offset).limit(limit).all()
            
            return alerts
        except Exception as e:
            logger.error(f"Error getting alerts: {str(e)}")
            return []
    
    async def update_alert_status(self, update_data: AlertStatusUpdate) -> AMLAlert:
        """
        알림 상태 업데이트 (비동기 지원)
        
        Args:
            update_data: 업데이트 데이터
            
        Returns:
            AMLAlert: 업데이트된 알림
        """
        try:
            # 알림 ID 확인
            if not update_data.alert_id:
                raise ValueError("Alert ID is required")
            
            # 알림 조회
            if self.is_async:
                query = select(AMLAlert).where(AMLAlert.id == update_data.alert_id)
                result = await self.db.execute(query)
                alert = result.scalars().first()
            else:
                alert = self.db.query(AMLAlert).filter(AMLAlert.id == update_data.alert_id).first()
            
            if not alert:
                raise ValueError(f"Alert {update_data.alert_id} not found")
            
            # 상태 업데이트
            alert.alert_status = update_data.status
            
            # 메모 업데이트
            if update_data.review_notes:
                alert.review_notes = update_data.review_notes
            
            # 검토자 업데이트
            if update_data.reviewed_by:
                alert.reviewed_by = update_data.reviewed_by
            
            # 검토 시간 업데이트
            alert.reviewed_at = datetime.utcnow()
            
            # 보고서 참조 업데이트
            if update_data.report_reference:
                alert.report_reference = update_data.report_reference
                
            # "reported" 상태로 변경된 경우 보고 시간 기록
            if update_data.status == AlertStatus.REPORTED and alert.reported_at is None:
                alert.reported_at = datetime.utcnow()

            alert.updated_at = datetime.utcnow() # 업데이트 시간 기록
            
            # DB 업데이트
            self.db.add(alert)
            
            if self.is_async:
                await self.db.commit()
                # 비동기 세션에서는 refresh 가 다르게 동작할 수 있으므로 필요시 조정
            else:
                self.db.commit()
                self.db.refresh(alert)
            
            return alert
        except Exception as e:
            if self.is_async:
                await self.db.rollback()
            else:
                self.db.rollback()
            logger.error(f"Error updating alert status: {str(e)}")
            raise
    
    async def create_alert(self, alert_data: AMLAlertCreate) -> AMLAlert:
        """
        수동으로 알림 생성
        
        Args:
            alert_data: 알림 생성 데이터
            
        Returns:
            AMLAlert: 생성된 알림
        """
        try:
            # 알림 객체 생성
            alert = AMLAlert(
                player_id=alert_data.player_id,
                partner_id=alert_data.partner_id,
                transaction_id=alert_data.transaction_id,
                alert_type=alert_data.alert_type,
                alert_severity=alert_data.alert_severity,
                alert_status=AlertStatus.NEW,
                description=alert_data.description,
                detection_rule=alert_data.detection_rule or "manual_creation",
                risk_score=alert_data.risk_score,
                transaction_ids=alert_data.transaction_ids,
                transaction_details=alert_data.transaction_details,
                risk_factors=alert_data.risk_factors,
                alert_data=alert_data.alert_data,
                created_at=datetime.utcnow()
            )
            
            # DB에 저장
            self.db.add(alert)
            
            if self.is_async:
                await self.db.flush()
            else:
                self.db.flush()
            
            logger.info(f"Manually created AML alert: {alert.id}")
            
            return alert
        except Exception as e:
            logger.error(f"Error creating alert: {str(e)}")
            raise
    
    async def get_alert(self, alert_id: int) -> Optional[AMLAlert]:
        """
        특정 알림 상세 정보 조회
        
        Args:
            alert_id: 알림 ID
            
        Returns:
            Optional[AMLAlert]: 알림 객체 또는 None
        """
        try:
            if self.is_async:
                query = select(AMLAlert).where(AMLAlert.id == alert_id)
                result = await self.db.execute(query)
                alert = result.scalars().first()
            else:
                alert = self.db.query(AMLAlert).filter(AMLAlert.id == alert_id).first()
            return alert
        except Exception as e:
            logger.error(f"Error getting alert {alert_id}: {str(e)}")
            return None

    async def get_player_alerts(
        self, 
        player_id: str, 
        limit: int = 50, 
        offset: int = 0
    ) -> List[AMLAlert]:
        """
        플레이어 관련 알림 조회 (비동기 지원)
        
        Args:
            player_id: 플레이어 ID
            limit: 페이징 제한
            offset: 페이징 오프셋
            
        Returns:
            List[AMLAlert]: 알림 목록
        """
        try:
            if self.is_async:
                query = select(AMLAlert).filter(
                    AMLAlert.player_id == player_id
                ).order_by(
                    desc(AMLAlert.created_at)
                ).offset(offset).limit(limit)
                result = await self.db.execute(query)
                alerts = result.scalars().all()
            else:
                alerts = self.db.query(AMLAlert).filter(
                    AMLAlert.player_id == player_id
                ).order_by(
                    desc(AMLAlert.created_at)
                ).offset(offset).limit(limit).all()
            
            return alerts
        except Exception as e:
            logger.error(f"Error getting player alerts: {str(e)}")
            return []
    
    async def get_high_risk_players(self, limit: int = 50, offset: int = 0) -> List[AMLRiskProfile]:
        """
        고위험 플레이어 목록 조회 (비동기 지원)
        
        Args:
            limit: 페이징 제한
            offset: 페이징 오프셋
            
        Returns:
            List[AMLRiskProfile]: 위험 프로필 목록
        """
        try:
            # 위험 점수 60 이상을 고위험으로 정의
            high_risk_threshold = 60.0
            
            if self.is_async:
                query = select(AMLRiskProfile).filter(
                    AMLRiskProfile.overall_risk_score >= high_risk_threshold,
                    AMLRiskProfile.is_active == True
                ).order_by(
                    desc(AMLRiskProfile.overall_risk_score)
                ).offset(offset).limit(limit)
                result = await self.db.execute(query)
                profiles = result.scalars().all()
            else:
                profiles = self.db.query(AMLRiskProfile).filter(
                    AMLRiskProfile.overall_risk_score >= high_risk_threshold,
                    AMLRiskProfile.is_active == True
                ).order_by(
                    desc(AMLRiskProfile.overall_risk_score)
                ).offset(offset).limit(limit).all()
            
            return profiles
        except Exception as e:
            logger.error(f"Error getting high risk players: {str(e)}")
            return []

    async def get_player_risk_profile_public(self, player_id: str) -> Optional[AMLRiskProfile]:
        """
        플레이어 위험 프로필 조회 (공개 메소드)
        존재하지 않으면 생성하지 않고 None 반환
        
        Args:
            player_id: 플레이어 ID
            
        Returns:
            Optional[AMLRiskProfile]: 위험 프로필 또는 None
        """
        try:
            # 파트너 ID는 현재 로직에서 필수가 아니므로 None 전달 가능
            # 필요하다면 player_id로 partner_id 조회 로직 추가
            risk_profile = await self._get_or_create_risk_profile(player_id, partner_id=None, create_if_not_found=False)
            return risk_profile
        except Exception as e:
            logger.error(f"Error getting player risk profile {player_id}: {str(e)}")
            return None
            
    async def create_report(self, report_request: 'AMLReportRequest', created_by: str) -> AMLReport:
        """
        AML 보고서 생성 (공개 메소드)
        
        Args:
            report_request: 보고서 요청 데이터 (스키마)
            created_by: 생성자 ID
            
        Returns:
            AMLReport: 생성된 보고서 객체
        """
        # report_request 스키마를 사용하여 _create_aml_report 호출 준비
        # _create_aml_report 는 alert_id 또는 transaction/analysis_result 를 받음
        # report_request 에 alert_id가 있으면 그것을 사용
        
        if report_request.alert_id:
             return await self._create_aml_report(
                 alert_id=report_request.alert_id, 
                 created_by=created_by
             )
        else:
             # alert_id 없이 보고서를 생성하는 로직이 필요하다면 여기에 추가
             # 예: 특정 플레이어 또는 트랜잭션 집합에 대한 보고서
             # 현재 구현은 alert_id 기반이므로, alert_id 없이는 에러 발생시킴
             logger.error("Report creation requires an alert_id in the current implementation.")
             raise ValueError("Report creation currently requires an associated alert_id.")

    async def _get_or_create_risk_profile(
        self, 
        player_id: str, 
        partner_id: Optional[str] = None, 
        create_if_not_found: bool = True
    ) -> Optional[AMLRiskProfile]:
        """
        플레이어 위험 프로필 조회 또는 생성 (create_if_not_found 옵션 추가)
        
        Args:
            player_id: 플레이어 ID
            partner_id: 파트너 ID (선택사항)
            create_if_not_found: 프로필이 없을 때 생성할지 여부
            
        Returns:
            Optional[AMLRiskProfile]: 위험 프로필 또는 None
        """
        # 위험 프로필 조회
        try:
            if self.is_async:
                query = select(AMLRiskProfile).where(AMLRiskProfile.player_id == player_id)
                result = await self.db.execute(query)
                risk_profile = result.scalars().first()
            else:
                risk_profile = self.db.query(AMLRiskProfile).filter(
                    AMLRiskProfile.player_id == player_id
                ).first()
            
            if risk_profile:
                return risk_profile
            elif create_if_not_found:
                # 프로필 생성
                logger.info(f"Creating new risk profile for player {player_id}")
                risk_profile = AMLRiskProfile(
                    player_id=player_id,
                    partner_id=partner_id,
                    overall_risk_score=30.0,  # 초기 위험도 (낮음)
                    deposit_risk_score=0.0,
                    withdrawal_risk_score=0.0,
                    gameplay_risk_score=0.0,
                    is_active=True,
                    deposit_count_7d=0,
                    deposit_amount_7d=0.0,
                    withdrawal_count_7d=0,
                    withdrawal_amount_7d=0.0,
                    deposit_count_30d=0,
                    deposit_amount_30d=0.0,
                    withdrawal_count_30d=0,
                    withdrawal_amount_30d=0.0,
                    wager_to_deposit_ratio=0.0,
                    withdrawal_to_deposit_ratio=0.0,
                    risk_factors={},
                    risk_mitigation={},
                    created_at=datetime.utcnow(),
                    last_assessment_at=datetime.utcnow()
                )
                
                # 트랜잭션 통계 계산 (비동기/동기 분기 필요)
                await self._calculate_transaction_stats(risk_profile) # Assuming _calculate_transaction_stats is async
                
                self.db.add(risk_profile)
                if self.is_async:
                    await self.db.flush()
                    # 비동기 세션에서는 refresh가 필요하지 않을 수 있음
                else:
                    self.db.flush()
                    self.db.refresh(risk_profile) # Refresh needed for sync session after flush
                
                return risk_profile
            else:
                # 생성하지 않고 None 반환
                return None
        except Exception as e:
            logger.error(f"Error getting or creating risk profile for player {player_id}: {str(e)}")
            # 필요시 rollback 처리
            if self.is_async:
                await self.db.rollback()
            else:
                self.db.rollback()
            raise # 혹은 None 반환
            
    async def _calculate_transaction_stats(self, risk_profile: AMLRiskProfile) -> None:
        """
        위험 프로필 트랜잭션 통계 계산 (비동기/동기 DB 접근 처리)
        
        Args:
            risk_profile: 위험 프로필
        """
        # 30일 기간 설정
        end_date = datetime.utcnow()
        start_date_30d = end_date - timedelta(days=30)
        start_date_7d = end_date - timedelta(days=7)

        # 공통 필터 조건
        base_filters = [
            Transaction.player_id == risk_profile.player_id,
            Transaction.status == TransactionStatus.COMPLETED
        ]

        # 30일 입금 통계
        deposit_stats_30d = await self._get_transaction_stats(
            base_filters + [
                Transaction.transaction_type == TransactionType.DEPOSIT,
                Transaction.created_at.between(start_date_30d, end_date)
            ]
        )
        risk_profile.deposit_count_30d = deposit_stats_30d['count']
        risk_profile.deposit_amount_30d = deposit_stats_30d['amount']
        
        # 7일 입금 통계
        deposit_stats_7d = await self._get_transaction_stats(
            base_filters + [
                Transaction.transaction_type == TransactionType.DEPOSIT,
                Transaction.created_at.between(start_date_7d, end_date)
            ]
        )
        risk_profile.deposit_count_7d = deposit_stats_7d['count']
        risk_profile.deposit_amount_7d = deposit_stats_7d['amount']

        # 30일 출금 통계
        withdrawal_stats_30d = await self._get_transaction_stats(
            base_filters + [
                Transaction.transaction_type == TransactionType.WITHDRAWAL,
                Transaction.created_at.between(start_date_30d, end_date)
            ]
        )
        risk_profile.withdrawal_count_30d = withdrawal_stats_30d['count']
        risk_profile.withdrawal_amount_30d = withdrawal_stats_30d['amount']

        # 7일 출금 통계
        withdrawal_stats_7d = await self._get_transaction_stats(
            base_filters + [
                Transaction.transaction_type == TransactionType.WITHDRAWAL,
                Transaction.created_at.between(start_date_7d, end_date)
            ]
        )
        risk_profile.withdrawal_count_7d = withdrawal_stats_7d['count']
        risk_profile.withdrawal_amount_7d = withdrawal_stats_7d['amount']

        # 30일 베팅 통계
        bet_stats_30d = await self._get_transaction_stats(
            base_filters + [
                Transaction.transaction_type == TransactionType.BET,
                Transaction.created_at.between(start_date_30d, end_date)
            ]
        )
        bet_amount_30d = bet_stats_30d['amount']
        
        # 베팅 대 입금 비율 계산 (30일 기준)
        if risk_profile.deposit_amount_30d > 0:
            risk_profile.wager_to_deposit_ratio = bet_amount_30d / risk_profile.deposit_amount_30d
        else:
            risk_profile.wager_to_deposit_ratio = 0
            
        # 출금 대 입금 비율 계산 (30일 기준)
        if risk_profile.deposit_amount_30d > 0:
             risk_profile.withdrawal_to_deposit_ratio = risk_profile.withdrawal_amount_30d / risk_profile.deposit_amount_30d
        else:
             risk_profile.withdrawal_to_deposit_ratio = 0
            
        # 총 트랜잭션 수 계산 (30일 기준)
        if self.is_async:
            tx_count_query = select(func.count(Transaction.id)).filter(
                Transaction.player_id == risk_profile.player_id,
                Transaction.created_at.between(start_date_30d, end_date)
            )
            tx_count_result = await self.db.execute(tx_count_query)
            risk_profile.transaction_count = tx_count_result.scalar() or 0
        else:
             count_q = self.db.query(func.count(Transaction.id)).filter(
                 Transaction.player_id == risk_profile.player_id,
                 Transaction.created_at.between(start_date_30d, end_date)
             )
             risk_profile.transaction_count = count_q.scalar() or 0

    async def _get_transaction_stats(self, filters: List) -> Dict[str, Any]:
        """ Helper to get transaction count and amount sum based on filters """
        if self.is_async:
            query = select(
                func.count(Transaction.id).label('count'),
                func.sum(Transaction.amount).label('amount')
            ).filter(and_(*filters))
            result = await self.db.execute(query)
            stats = result.first()
        else:
            query = self.db.query(
                func.count(Transaction.id).label('count'),
                func.sum(Transaction.amount).label('amount')
            ).filter(and_(*filters))
            stats = query.first()
            
        return {
            'count': stats.count if stats else 0,
            'amount': float(stats.amount) if stats and stats.amount is not None else 0.0
        }
