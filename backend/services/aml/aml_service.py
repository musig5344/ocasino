"""
자금세탁방지(AML) 서비스
트랜잭션 모니터링, 위험 평가, 보고 등 AML 관련 비즈니스 로직 담당
"""
import logging
from uuid import UUID, uuid4
from typing import Optional, Dict, Any, List, Tuple, Union, TYPE_CHECKING, cast
from datetime import datetime, timedelta
from decimal import Decimal
import json
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, and_, or_, desc, select, case, text, insert
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.models.aml import (
    AMLAlert, AMLRiskProfile, AMLReport, AMLTransaction,
    AlertType, AlertStatus, AlertSeverity, ReportType, ReportingJurisdiction
)
from backend.repositories.wallet_repository import WalletRepository
from backend.schemas.aml import AMLAlertCreate, AlertStatusUpdate
# Import encryption utility
from backend.utils.encryption import get_encryptor

# TYPE_CHECKING 블록 추가
if TYPE_CHECKING:
    from backend.models.domain.wallet import Transaction, TransactionType, TransactionStatus

logger = logging.getLogger(__name__)

class DatabaseError(Exception):
    """데이터베이스 관련 예외"""
    pass

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
        
        # 패턴 분석 임계값 설정
        self.pattern_thresholds = {
            "behavior_min_records": 10, # 행동 패턴 분석 최소 거래 건수
            "time_min_records": 5,      # 시간 패턴 분석 최소 거래 건수
            "amount_min_records": 5,    # 금액 패턴 분석 최소 거래 건수
            "time_activity_percent": 0.1, # 정상 시간/요일 결정 최소 활동 비율 (10%)
            "amount_z_score": 2.5,       # 금액 편차 Z-score 임계값
            "frequency_ratio": 3.0,      # 빈도 비율 임계값
            "frequency_min_count": 3       # 빈도 편차 최소 일일 거래 건수
        }
        
        # 고위험 국가 목록
        self.high_risk_countries = [
            "AF", "BY", "BI", "CF", "CD", "KP", "ER", "IR", "IQ", "LY", 
            "ML", "MM", "NI", "PK", "RU", "SO", "SS", "SD", "SY", "VE", 
            "YE", "ZW"
        ]
    
    async def _get_historical_transactions(self, player_id: str, partner_id: str,
                                           transaction_type: Optional['TransactionType'] = None,
                                           start_time: Optional[datetime] = None,
                                           end_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """지정된 기간 및 유형의 플레이어 거래 내역 조회 (구현 필요)"""
        # TODO: 실제 DB에서 거래 내역을 조회하는 로직 구현 (WalletRepository 사용)
        # 예시 구현:
        # if not start_time:
        #     start_time = datetime.now(timezone.utc) - timedelta(days=30)
        # if not end_time:
        #     end_time = datetime.now(timezone.utc)
        # return await self.wallet_repo.get_player_transactions(
        #     player_id=player_id, partner_id=partner_id, transaction_type=transaction_type,
        #     start_time=start_time, end_time=end_time
        # )

        logger.warning(f"AMLService._get_historical_transactions called with type={transaction_type}, start={start_time}, end={end_time}. Not fully implemented. Returning empty list.")
        return [] # 임시로 빈 리스트 반환

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
        기존 분석 결과 조회 (analysis_details 복호화 포함)
        
        Args:
            transaction_id: 트랜잭션 ID
            
        Returns:
            Optional[Dict[str, Any]]: 분석 결과 또는 None
        """
        decrypted_details = None # Variable to hold decrypted data
        try:
            if self.is_async:
                query = select(AMLTransaction).where(AMLTransaction.transaction_id == str(transaction_id))
                result = await self.db.execute(query)
                aml_transaction = result.scalars().first()
            else:
                aml_transaction = self.db.query(AMLTransaction).filter(
                    AMLTransaction.transaction_id == str(transaction_id)
                ).first()
            
            if aml_transaction:
                # Decrypt analysis_details if it exists and is in expected format
                if aml_transaction.analysis_details and isinstance(aml_transaction.analysis_details, dict):
                    encrypted_data = aml_transaction.analysis_details.get("encrypted_data")
                    if encrypted_data:
                        try:
                            encryptor = get_encryptor()
                            decrypted_json_string = encryptor.decrypt(encrypted_data)
                            if decrypted_json_string:
                                decrypted_details = json.loads(decrypted_json_string)
                            else:
                                logger.warning(f"Decryption returned None for analysis_details of tx {transaction_id}.")
                        except json.JSONDecodeError as jde:
                            logger.error(f"Failed to decode JSON after decrypting analysis_details for tx {transaction_id}: {jde}")
                        except Exception as e:
                            logger.exception(f"Failed to decrypt analysis_details for tx {transaction_id}: {e}")
                    else:
                        logger.warning(f"analysis_details for tx {transaction_id} missing 'encrypted_data' key.")
                else:
                    logger.warning(f"analysis_details for tx {transaction_id} is missing or not a dict.")

                # Construct the result, replacing encrypted data with decrypted if successful
                return {
                    "transaction_id": str(aml_transaction.transaction_id), # Ensure string conversion
                    "player_id": str(aml_transaction.player_id),
                    "partner_id": str(aml_transaction.partner_id),
                    "risk_score": aml_transaction.risk_score,
                    "risk_factors": aml_transaction.risk_factors,
                    # Use decrypted_details if available, otherwise keep original (encrypted/malformed) or None
                    "analysis_details": decrypted_details if decrypted_details is not None else aml_transaction.analysis_details,
                    "is_large_transaction": aml_transaction.is_large_transaction,
                    "is_suspicious_pattern": aml_transaction.is_suspicious_pattern,
                    "is_unusual_for_player": aml_transaction.is_unusual_for_player,
                    "is_structuring_attempt": aml_transaction.is_structuring_attempt,
                    "is_regulatory_report_required": aml_transaction.is_regulatory_report_required,
                    "alert_id": aml_transaction.alert_id,
                    "created_at": aml_transaction.created_at.isoformat()
                }
            return None # No AMLTransaction record found
        except Exception as e:
            logger.exception(f"Error getting existing analysis for tx {transaction_id}: {e}")
            # Decide if this should return None or raise an error
            return None
    
    async def _perform_analysis(self, transaction: 'Transaction', risk_profile: AMLRiskProfile) -> Dict[str, Any]:
        """트랜잭션 위험 분석 수행"""
        # 메서드 시작 시점에 실제 필요한 클래스 임포트
        from backend.models.domain.wallet import Transaction, TransactionType, TransactionStatus

        # 분석 결과 초기화
        analysis_result = {
            "transaction_id": str(transaction.id),
            "player_id": str(transaction.player_id),
            "amount": float(transaction.amount),
            "currency": transaction.currency,
            "transaction_type": transaction.transaction_type,
            "risk_score": 0.0, # float으로 초기화
            "risk_factors": {},
            "requires_alert": False,
            "requires_report": False,
            "alert_type": None,
            "alert_priority": None,
            "threshold": self.thresholds.get(transaction.currency, self.thresholds["default"]) # 임계값 추가
        }

        # 위험 요소 분석
        # 1. 고액 거래 확인
        is_large_transaction = self._check_large_transaction(transaction)
        if is_large_transaction:
            analysis_result["risk_factors"]["large_transaction"] = {"threshold": analysis_result["threshold"]}
            analysis_result["risk_score"] += 40
            analysis_result["is_large_transaction"] = True # 플래그 설정

        # 2. 행동 패턴 이탈 확인
        pattern_deviation = await self._check_behavior_pattern_deviation(transaction, risk_profile)
        if pattern_deviation["deviation_detected"]:
            # details 딕셔너리에서 각 편차 결과를 가져옴
            details_dict = pattern_deviation.get("details", {})
            time_dev_result = details_dict.get("time_deviation", {})
            amount_dev_result = details_dict.get("amount_deviation", {})
            freq_dev_result = details_dict.get("frequency_deviation", {})

            analysis_result["risk_factors"]["pattern_deviation"] = {
                 # 각 편차 결과 딕셔너리에서 'deviation_detected' 값을 가져옴
                 "time_deviation": time_dev_result.get("deviation_detected", False),
                 "amount_deviation": amount_dev_result.get("deviation_detected", False),
                 "frequency_deviation": freq_dev_result.get("deviation_detected", False),
                 # 전체 details는 그대로 유지
                 "details": details_dict
            }
            analysis_result["risk_score"] += 25 * pattern_deviation["severity"]
            analysis_result["is_unusual_for_player"] = True # 플래그 설정

        # 3. 복합 위험 점수 계산 (다른 위험 요소 분석 후 호출)
        # Convert risk_factors dict to a fully hashable tuple using the recursive helper
        hashable_risk_factors = self._dict_to_hashable(analysis_result["risk_factors"])
        composite_risk = self._calculate_composite_risk(hashable_risk_factors) # Pass the hashable tuple
        analysis_result["risk_score"] += composite_risk

        # 위험 점수 상한 설정
        analysis_result["risk_score"] = min(100.0, analysis_result["risk_score"])

        # 알림 타입 설정
        if analysis_result["risk_factors"]:
            analysis_result["alert_type"] = self._determine_alert_type(analysis_result["risk_factors"])
        else:
            # 위험 요소가 없으면 알림 타입도 없음
            analysis_result["alert_type"] = None

        # 알림 우선순위 설정
        if analysis_result["risk_score"] > 0:
            analysis_result["alert_priority"] = self._calculate_alert_priority(
                analysis_result["risk_score"],
                analysis_result["risk_factors"]
            )
        else:
            # 위험 점수가 0 이하면 우선순위 없음
            analysis_result["alert_priority"] = None

        # 알림 필요 여부 결정 (예: 위험 점수 40점 이상)
        alert_threshold = 40.0
        analysis_result["requires_alert"] = analysis_result["risk_score"] >= alert_threshold

        # 규제 보고 필요 여부 결정 (예: 고액 거래 또는 위험 점수 75점 이상)
        report_threshold = 75.0
        analysis_result["requires_report"] = is_large_transaction or analysis_result["risk_score"] >= report_threshold
        analysis_result["is_regulatory_report_required"] = analysis_result["requires_report"] # 플래그 설정

        # 디버깅 로그
        logger.debug(f"Analysis result for transaction {transaction.id}: {analysis_result}")

        return analysis_result

    def _check_large_transaction(self, transaction: 'Transaction') -> bool:
        """고액 거래 여부 확인"""
        threshold = self.thresholds.get(transaction.currency, self.thresholds["default"])
        return float(transaction.amount) >= threshold

    async def _check_behavior_pattern_deviation(self, transaction: 'Transaction', risk_profile: AMLRiskProfile) -> Dict[str, Any]:
        """
        Comprehensive behavior pattern analysis comparing current transaction against
        player's established behavior patterns
        
        Args:
            transaction: Transaction to analyze
            risk_profile: Player's risk profile
            
        Returns:
            Dict[str, Any]: Analysis results with deviation details
        """
        logger.debug(f"Starting behavior pattern analysis for transaction {transaction.id}")
        
        result = {
            "deviation_detected": False,
            "severity": 0,
            "details": {}
        }
        
        # Need enough transaction history to establish patterns
        if risk_profile.transaction_count < self.pattern_thresholds["behavior_min_records"]:
            result["details"]["insufficient_history"] = True
            logger.debug(f"Insufficient transaction history for player {transaction.player_id}: {risk_profile.transaction_count} < {self.pattern_thresholds['behavior_min_records']}")
            return result
        
        # Check time patterns (when player typically transacts)
        time_result = await self._check_time_pattern_deviation(transaction, risk_profile)
        time_deviation = time_result.get('deviation_detected', False)
        
        # Check amount patterns (typical transaction amounts)
        amount_result = await self._check_amount_pattern_deviation(transaction, risk_profile)
        amount_deviation = amount_result.get('deviation_detected', False)
        
        # Check frequency patterns (how often player transacts)
        frequency_result = await self._check_frequency_pattern_deviation(transaction, risk_profile)
        frequency_deviation = frequency_result.get('deviation_detected', False)
        
        # Track which pattern types show deviations
        deviations_found = []
        
        if time_deviation:
            deviations_found.append("time")
            result["details"]["time_deviation"] = time_result
        
        if amount_deviation:
            deviations_found.append("amount")
            result["details"]["amount_deviation"] = amount_result
        
        if frequency_deviation:
            deviations_found.append("frequency")
            result["details"]["frequency_deviation"] = frequency_result
        
        # Calculate overall deviation result
        result["deviation_detected"] = len(deviations_found) > 0
        
        # Calculate severity based on number of deviating patterns
        result["severity"] = min(1.0, len(deviations_found) / 3.0)
        
        # Include patterns analyzed and which showed deviations
        result["details"]["patterns_analyzed"] = ["time", "amount", "frequency"]
        result["details"]["deviations_found"] = deviations_found
        
        logger.debug(f"Behavior pattern analysis for transaction {transaction.id}: deviation_detected={result['deviation_detected']}, severity={result['severity']}, deviations={deviations_found}")
        
        return result

    async def _check_time_pattern_deviation(self, transaction: 'Transaction', risk_profile: AMLRiskProfile) -> Dict[str, Any]:
        """
        Analyze if transaction timing deviates from player's normal patterns.
        Ensures return format consistency: {'deviation_detected': bool, 'details': dict}
        """
        logger.debug(f"Starting time pattern analysis for transaction {transaction.id}")
        
        # Get transaction history
        start_time = transaction.created_at - timedelta(days=30)
        transactions = await self._get_historical_transactions(
            transaction.player_id,
            transaction.partner_id,
            transaction.transaction_type,
            start_time,
            transaction.created_at
        )
        
        # Not enough data to establish pattern
        min_records_threshold = self.pattern_thresholds["time_min_records"]
        if len(transactions) < min_records_threshold:
            logger.debug(f"Insufficient time pattern data for player {transaction.player_id}: {len(transactions)} < {min_records_threshold}")
            return {"deviation_detected": False, "details": {"insufficient_data": True}}
        
        # Analyze hour of day patterns
        hour_distribution = {}
        for tx in transactions:
            hour = tx.created_at.hour
            hour_distribution[hour] = hour_distribution.get(hour, 0) + 1
        
        # Determine player's normal hours (hours with at least N% of activity)
        total_txs = len(transactions)
        min_activity_ratio = self.pattern_thresholds["time_activity_percent"]
        normal_hours = [hour for hour, count in hour_distribution.items() 
                       if count >= max(1, total_txs * min_activity_ratio)]
        
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
                       if count >= max(1, total_txs * min_activity_ratio)]
        
        current_day = transaction.created_at.weekday()
        unusual_day = current_day not in normal_days
        
        # Conditional checks
        is_unusual_time_and_day = (unusual_time and unusual_day)
        is_unusual_time_with_no_history = (unusual_time and hour_distribution.get(current_hour, 0) == 0)
        
        # Deviation detected if both time and day are unusual, or if time is highly unusual
        deviation_detected = is_unusual_time_and_day or is_unusual_time_with_no_history
        
        # Ensure consistent return format
        result = {
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
        
        logger.debug(f"Time pattern result for transaction {transaction.id}: deviation_detected={deviation_detected}")
        
        return result

    async def _check_amount_pattern_deviation(self, transaction: 'Transaction', risk_profile: AMLRiskProfile) -> Dict[str, Any]:
        """
        Analyze if transaction amount deviates from player's normal patterns
        
        Args:
            transaction: Transaction to analyze
            risk_profile: Player's risk profile
            
        Returns:
            Dict[str, Any]: Amount pattern analysis result
        """
        logger.debug(f"Starting amount pattern analysis for transaction {transaction.id}")
        
        # Get transaction history
        start_time = transaction.created_at - timedelta(days=30)
        transactions = await self._get_historical_transactions(
            transaction.player_id,
            transaction.partner_id,
            transaction.transaction_type,
            start_time,
            transaction.created_at
        )
        
        # Not enough data to establish pattern
        if len(transactions) < self.pattern_thresholds["amount_min_records"]:
            logger.debug(f"Insufficient amount pattern data for player {transaction.player_id}: {len(transactions)} < {self.pattern_thresholds['amount_min_records']}")
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
        z_score_threshold = self.pattern_thresholds["amount_z_score"]
        deviation_detected = (abs(z_score) > z_score_threshold or 
                             current_amount < min_amount or 
                             current_amount > max_amount)
        
        result = {
            "deviation_detected": deviation_detected,
            "details": {
                "current_amount": current_amount,
                "avg_amount": avg_amount,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "std_deviation": std_dev,
                "z_score": z_score,
                "z_score_threshold": z_score_threshold,
                "outside_range": current_amount < min_amount or current_amount > max_amount,
                "amount_distribution": bins,
                "current_bin": current_bin
            }
        }
        
        logger.debug(f"Amount pattern result for transaction {transaction.id}: deviation_detected={deviation_detected}, z_score={z_score}")
        
        return result

    async def _check_frequency_pattern_deviation(self, transaction: 'Transaction', risk_profile: AMLRiskProfile) -> Dict[str, Any]:
        """
        Analyze if transaction frequency deviates from player's normal patterns
        
        Args:
            transaction: Transaction to analyze
            risk_profile: Player's risk profile
            
        Returns:
            Dict[str, Any]: Frequency pattern analysis result
        """
        logger.debug(f"Starting frequency pattern analysis for transaction {transaction.id}")
        
        # Calculate average transaction frequencies over different periods
        # Last 24 hours
        day_start = transaction.created_at - timedelta(days=1)
        day_txs = await self._get_historical_transactions(
            transaction.player_id,
            transaction.partner_id,
            transaction.transaction_type,
            day_start,
            transaction.created_at
        )

        # Last 7 days (excluding last 24 hours)
        week_start = transaction.created_at - timedelta(days=7)
        week_txs = await self._get_historical_transactions(
            transaction.player_id,
            transaction.partner_id,
            transaction.transaction_type,
            week_start,
            day_start # End time is day_start here
        )

        # Last 30 days (excluding last 7 days)
        month_start = transaction.created_at - timedelta(days=30)
        month_txs = await self._get_historical_transactions(
            transaction.player_id,
            transaction.partner_id,
            transaction.transaction_type,
            month_start,
            week_start # End time is week_start here
        )

        # Calculate frequencies
        day_count = len(day_txs)
        week_count = len(week_txs)
        month_count = len(month_txs)

        # Calculate average daily frequencies
        week_daily_avg = week_count / 6.0 if week_count > 0 else 0.0 
        month_daily_avg = month_count / 23.0 if month_count > 0 else 0.0 

        # Account for players with limited history
        if week_count == 0 and month_count == 0:
            logger.debug(f"Insufficient frequency pattern data for player {transaction.player_id}")
            return {"deviation_detected": False, 
                    "details": {"insufficient_data": True, 
                                "current_24h_count": day_count,
                                "past_week_count": week_count,
                                "past_month_count": month_count}}

        # Use maximum average as baseline (more conservative)
        baseline_daily_avg = max(week_daily_avg, month_daily_avg, 0.1)  # Minimum to avoid division by zero

        # Calculate frequency ratio
        frequency_ratio = day_count / baseline_daily_avg if baseline_daily_avg > 0 else 0 

        # Deviation detected if today's frequency is significantly higher
        ratio_threshold = self.pattern_thresholds["frequency_ratio"]
        min_count_threshold = self.pattern_thresholds["frequency_min_count"]
        deviation_detected = frequency_ratio > ratio_threshold and day_count > min_count_threshold

        result = {
            "deviation_detected": deviation_detected,
            "details": {
                "current_24h_count": day_count,
                "past_week_count": week_count,
                "past_month_count": month_count,
                "avg_daily_past_week": week_daily_avg,
                "avg_daily_past_month": month_daily_avg,
                "baseline_daily_avg": baseline_daily_avg,
                "frequency_ratio": frequency_ratio,
                "threshold_ratio": ratio_threshold,
                "threshold_min_count": min_count_threshold
            }
        }
        
        logger.debug(f"Frequency pattern result for transaction {transaction.id}: deviation_detected={deviation_detected}, ratio={frequency_ratio}")
        
        return result
    
    def _dict_to_hashable(self, d):
        """딕셔너리를 해시 가능한 형태로 재귀적으로 변환"""
        if isinstance(d, dict):
            # 키-값 쌍을 정렬하고 값을 재귀적으로 변환하여 튜플 생성
            return tuple(sorted((k, self._dict_to_hashable(v)) for k, v in d.items()))
        elif isinstance(d, list):
            # 리스트의 각 항목을 재귀적으로 변환하여 튜플 생성
            return tuple(self._dict_to_hashable(x) for x in d)
        # 다른 타입(int, float, str, bool, None 등)은 그대로 반환
        return d

    @lru_cache(maxsize=64)
    def _calculate_composite_risk(self, risk_factors_tuple: tuple) -> float:
        """
        Calculate additional risk based on combinations of risk factors that
        together represent higher risk than each factor individually
        
        Args:
            risk_factors_tuple: Tuple representation of risk factors for caching
            
        Returns:
            float: Additional risk score from combined factors
        """
        # Convert tuple back to dict for processing
        risk_factors = {k: v for k, v in risk_factors_tuple}
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
            "multi_account",        # Multi-account activity
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
            "multi_account": AlertType.PATTERN,
            "structuring": AlertType.PATTERN,
            "large_transaction": AlertType.THRESHOLD,
            "rapid_movement": AlertType.PATTERN,
            "unusual_betting": AlertType.PATTERN,
            "high_risk_country": AlertType.BLACKLIST,
            "pattern_deviation": AlertType.PATTERN,
            "low_wagering": AlertType.PATTERN
        }
        
        # Return highest priority factor present
        for factor in priority_factors:
            if factor in risk_factors:
                return type_mapping.get(factor, AlertType.OTHER)
        
        # Default alert type if no specific factors identified
        return AlertType.OTHER

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
    
    async def _create_alert(self, transaction: 'Transaction', analysis_result: Dict[str, Any]) -> AMLAlert:
        """
        Create a detailed AML alert with comprehensive analysis results
        
        Args:
            transaction: Transaction that triggered the alert
            analysis_result: Detailed risk analysis results
            
        Returns:
            AMLAlert: Created alert record
        """
        try:
            # 알림 유형과 우선순위 변환
            alert_type_str = analysis_result.get("alert_type", "OTHER")
            if isinstance(alert_type_str, str):
                alert_type = getattr(AlertType, alert_type_str.upper()) if hasattr(AlertType, alert_type_str.upper()) else AlertType.OTHER
            else:
                alert_type = alert_type_str  # Already an AlertType enum
            
            priority_str = analysis_result.get("alert_priority", "MEDIUM")
            if isinstance(priority_str, str):
                priority = getattr(AlertSeverity, priority_str.upper()) if hasattr(AlertSeverity, priority_str.upper()) else AlertSeverity.MEDIUM
            else:
                priority = priority_str  # Already an AlertSeverity enum
            
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
            
            return alert
        except Exception as e:
            logger.exception(f"Error creating AML alert for transaction {transaction.id}: {e}")
            raise
    
    def _generate_alert_description(self, analysis_result: Dict[str, Any]) -> str:
        """
        Generate detailed human-readable alert description for investigators
        
        Args:
            analysis_result: Risk analysis results
            
        Returns:
            str: Formatted alert description
        """
        alert_type_raw = analysis_result["alert_type"]
        # Handle both string and enum types
        if isinstance(alert_type_raw, str):
            alert_type = alert_type_raw
        else:
            # Assuming it's an AlertType enum
            alert_type = str(alert_type_raw).split('.')[-1].lower()
            
        risk_score = analysis_result["risk_score"]
        
        # Format risk factors for description
        risk_factors = list(analysis_result["risk_factors"].keys())
        risk_factors_str = ", ".join(factor.replace("_", " ").title() 
                                  for factor in risk_factors)
        
        # Base description
        base_desc = (f"{alert_type.replace('_', ' ').title()} detected with "
                   f"risk score {risk_score:.0f}/100")
        
        # Add specific details based on alert type
        if alert_type == "large_transaction" or "large_transaction" in risk_factors:
            amount = analysis_result["amount"]
            currency = analysis_result["currency"]
            threshold = analysis_result["threshold"]
            detail = (f"Transaction of {amount} {currency} exceeded threshold "
                    f"of {threshold} {currency}")
        elif alert_type == "structuring" or "structuring" in risk_factors:
            struct_details = analysis_result["risk_factors"].get("structuring", {}).get("details", {})
            count = struct_details.get("total_suspicious_count", 0)
            detail = (f"Pattern of {count} transactions just below reporting threshold "
                    f"detected within 48 hours")
        elif alert_type == "rapid_movement" or "rapid_movement" in risk_factors:
            rm_details = analysis_result["risk_factors"].get("rapid_movement", {}).get("details", {})
            ratio = rm_details.get("withdrawal_to_deposit_ratio", 0) * 100
            detail = (f"Withdrawal of {ratio:.0f}% of recent deposits within 24 hours "
                    f"of deposit")
        elif alert_type == "unusual_betting" or "unusual_betting" in risk_factors:
            bet_details = analysis_result["risk_factors"].get("unusual_betting", {}).get("details", {})
            unusual = bet_details.get("unusual_factors", {})
            if unusual.get("statistical_outlier"):
                detail = "Betting amount statistically inconsistent with player's history"
            elif unusual.get("sudden_increase"):
                detail = "Sudden significant increase in betting amount"
            elif unusual.get("unusual_game"):
                detail = "Betting on games rarely played by this player"
            else:
                detail = "Unusual betting pattern detected"
        elif alert_type == "multi_account" or "multi_account" in risk_factors:
            ma_details = analysis_result["risk_factors"].get("multi_account", {}).get("details", {})
            count = ma_details.get("linked_account_count", 0)
            detail = f"Activity linked to {count} other accounts sharing identifiers"
        elif alert_type == "high_risk_country" or "high_risk_country" in risk_factors:
            country = analysis_result["risk_factors"].get("high_risk_country", {}).get("country", "unknown")
            detail = f"Transaction associated with high-risk country: {country}"
        elif alert_type == "pattern_deviation" or "pattern_deviation" in risk_factors:
            pd_details = analysis_result["risk_factors"].get("pattern_deviation", {}).get("details", {})
            deviations = pd_details.get("deviations_found", [])
            deviation_str = ", ".join(deviations)
            detail = f"Significant deviation from established patterns in: {deviation_str}"
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
        
        # 실제 구현에서는 알림 서비스 호출 코드 추가
    
    async def _update_risk_profile(
        self, risk_profile: AMLRiskProfile, transaction: 'Transaction', analysis_result: Dict[str, Any]
    ) -> None:
        """
        위험 프로필 업데이트
        
        Args:
            risk_profile: 위험 프로필
            transaction: 트랜잭션 객체
            analysis_result: 분석 결과
        """
        try:
            # 트랜잭션 유형에 따라 프로필 업데이트
            from backend.models.domain.wallet import TransactionType
            
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
            
            # 위험 점수 업데이트 - 가중 평균 적용
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
            current_time = datetime.utcnow().isoformat()
            for factor_key, factor_data in analysis_result["risk_factors"].items():
                if factor_key not in risk_profile.risk_factors:
                    risk_profile.risk_factors[factor_key] = {
                        "first_detected": current_time,
                        "count": 1,
                        "last_detected": current_time,
                        "details": factor_data
                    }
                else:
                    risk_profile.risk_factors[factor_key]["count"] += 1
                    risk_profile.risk_factors[factor_key]["last_detected"] = current_time
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
                
            logger.info(f"Updated risk profile for player {risk_profile.player_id}, new score: {risk_profile.overall_risk_score:.2f}")
            
        except Exception as e:
            logger.exception(f"Error updating risk profile for player {risk_profile.player_id}: {e}")
            raise
    
    async def _save_analysis_result(self, transaction_id: UUID, analysis_result: Dict[str, Any]) -> None:
        """
        분석 결과 저장
        
        Args:
            transaction_id: 트랜잭션 ID
            analysis_result: 분석 결과
        """
        # 분석 결과 로깅
        logger.info(f"Saved AML analysis for transaction {transaction_id}")
    
    async def _save_aml_transaction(self, transaction: 'Transaction', analysis_result: Dict[str, Any]) -> AMLTransaction:
        """분석된 트랜잭션 정보 저장 (analysis_details 암호화 포함)"""
        try:
            # 암호화 처리
            encryptor = get_encryptor()
            details_json_string = json.dumps(analysis_result)
            encrypted_details = encryptor.encrypt(details_json_string)
            encrypted_details_payload = {"encrypted_data": encrypted_details}

            # AML 트랜잭션 객체 생성
            aml_tx = AMLTransaction(
                transaction_id=str(transaction.id),
                player_id=str(transaction.player_id),
                partner_id=str(transaction.partner_id) if transaction.partner_id else None,
                risk_score=analysis_result.get("risk_score", 0.0),
                risk_factors=analysis_result.get("risk_factors", {}),
                analysis_details=encrypted_details_payload, 
                
                # 요약 플래그 설정
                is_large_transaction=analysis_result.get("is_large_transaction", False),
                is_suspicious_pattern=analysis_result.get("is_suspicious_pattern", False),
                is_unusual_for_player=analysis_result.get("is_unusual_for_player", False),
                is_structuring_attempt=analysis_result.get("is_structuring_attempt", False),
                is_regulatory_report_required=analysis_result.get("requires_report", False),
                
                alert_id=analysis_result.get("alert") # Optional alert ID
            )
            
            # DB에 저장
            self.db.add(aml_tx)
            
            if self.is_async:
                await self.db.flush()
            else:
                self.db.flush()
                
            logger.info(f"Saved AML transaction analysis for transaction ID: {transaction.id}")
            return aml_tx
            
        except Exception as e:
            logger.exception(f"Failed to save AML transaction for {transaction.id}: {e}")
            # 데이터베이스 오류 처리
            if isinstance(e, (IntegrityError, SQLAlchemyError)):
                raise DatabaseError(f"Database error when saving AML transaction {transaction.id}: {str(e)}") from e
            # 암호화 오류 등 기타 오류
            raise DatabaseError(f"Failed to save AML transaction {transaction.id}: {str(e)}") from e
    
    async def _create_aml_report(
        self, 
        alert_id: Optional[int] = None, 
        transaction: Optional['Transaction'] = None, 
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
        try:
            # 보고서 ID 생성
            report_id = f"REP-{uuid4().hex[:8].upper()}"
            
            # 내용 준비
            if alert_id is not None:
                # 알림에서 생성
                if self.is_async:
                    query = select(AMLAlert).where(AMLAlert.id == alert_id)
                    result = await self.db.execute(query)
                    alert = (await result.scalars()).first()
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
                
                # 알림 타입 처리 (문자열 또는 AlertType)
                alert_type = analysis_result.get("alert_type")
                if hasattr(alert_type, 'value'):  # AlertType enum
                    alert_type_str = str(alert_type.value)
                else:
                    alert_type_str = str(alert_type)
                
                report_data = {
                    "transaction_details": {
                        "id": str(transaction.id),
                        "amount": float(transaction.amount),
                        "currency": transaction.currency,
                        "transaction_type": transaction.transaction_type,
                        "created_at": transaction.created_at.isoformat()
                    },
                    "risk_factors": analysis_result["risk_factors"],
                    "alert_type": alert_type_str,
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
            
            # DB에 저장
            self.db.add(report)
            
            if self.is_async:
                await self.db.flush()
            else:
                self.db.flush()
            
            logger.info(f"Created AML report: {report.report_id}")
            
            return report
        except Exception as e:
            logger.exception(f"Error creating AML report: {e}")
            raise
    
    # API 서비스 메서드
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
                alerts = (await result.scalars()).all()
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
                alert = (await result.scalars()).first()
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