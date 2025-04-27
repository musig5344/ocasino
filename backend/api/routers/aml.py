from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime

from backend.database import get_db
from backend.models.aml import AMLAlert, AMLTransaction, AMLRiskProfile, AlertType, AlertStatus, AlertSeverity, ReportType, ReportingJurisdiction
from backend.schemas.aml import (
    AMLAlertCreate, AMLAlertResponse, AMLAlertDetailResponse, AlertStatusUpdate,
    AMLTransactionAnalysis, AMLRiskProfileResponse, AMLReportRequest, AMLReportResponse
)
from backend.services.aml_service import AMLService
from backend.utils.auth import get_current_user, get_current_player_id, get_admin_user
from backend.models.domain.wallet import Transaction
from backend.utils.kafka_producer import send_kafka_message

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aml", tags=["AML"])

def _convert_to_enum(value_str: str, enum_class: Any, default_value: Any) -> Any:
    """문자열을 Enum 값으로 변환"""
    if not value_str:
        return default_value
    
    value_str = value_str.upper()
    
    try:
        return getattr(enum_class, value_str)
    except AttributeError:
        return default_value

@router.post("/analyze-transaction/{transaction_id}", response_model=AMLTransactionAnalysis)
async def analyze_transaction(
    transaction_id: str,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    트랜잭션을 AML 관점에서 분석합니다 (관리자 전용).
    """
    aml_service = AMLService(db)
    
    try:
        # 트랜잭션 분석
        analysis_result = await aml_service.analyze_transaction(
            transaction_id=transaction_id, 
            user_id=user.get("id") or user.get("username")
        )
        
        if "error" in analysis_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=analysis_result["error"]
            )
        
        # 분석 결과를 Kafka로 전송 (비동기)
        background_tasks.add_task(
            send_kafka_message,
            "aml_transaction_analysis",
            {
                "transaction_id": transaction_id,
                "player_id": analysis_result["player_id"],
                "analysis_result": analysis_result,
                "analyzed_at": datetime.now().isoformat()
            }
        )
        
        # 응답 변환
        return AMLTransactionAnalysis(
            transaction_id=transaction_id,
            player_id=analysis_result["player_id"],
            is_large_transaction=analysis_result.get("is_large_transaction", False),
            is_suspicious_pattern=analysis_result.get("is_suspicious_pattern", False),
            is_unusual_for_player=analysis_result.get("is_unusual_for_player", False),
            is_structuring_attempt=analysis_result.get("is_structuring_attempt", False),
            is_regulatory_report_required=analysis_result.get("requires_report", False),
            risk_score=analysis_result["risk_score"],
            risk_factors=analysis_result["risk_factors"],
            regulatory_threshold_currency=analysis_result.get("currency", "USD"),
            regulatory_threshold_amount=analysis_result.get("threshold", 10000.0),
            reporting_jurisdiction=ReportingJurisdiction.MALTA,  # 기본값
            analysis_version="1.0.0",
            analysis_details={
                "is_politically_exposed_person": analysis_result.get("is_politically_exposed_person", False),
                "is_high_risk_jurisdiction": analysis_result.get("is_high_risk_jurisdiction", False),
                "alert_id": analysis_result.get("alert"),
                "report_id": analysis_result.get("report_id"),
                "analyzed_at": datetime.now().isoformat()
            }
        )
    except HTTPException as e:
        logger.error(f"트랜잭션 분석 중 HTTP 예외: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"트랜잭션 분석 중 오류 발생: {str(e)}")
        # 오류 세부 정보 로깅
        import traceback
        logger.error(traceback.format_exc())
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"트랜잭션 분석 중 오류가 발생했습니다: {str(e)[:100]}"
        )

@router.post("/alerts", response_model=AMLAlertResponse)
async def create_aml_alert(
    alert_data: AMLAlertCreate,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    AML 알림을 수동으로 생성합니다 (관리자 전용).
    """
    aml_service = AMLService(db)
    
    try:
        alert = await aml_service.create_alert(alert_data)
        
        return AMLAlertResponse(
            id=alert.id,
            player_id=alert.player_id,
            alert_type=alert.alert_type,
            alert_severity=alert.alert_severity,
            alert_status=alert.alert_status,
            description=alert.description,
            detection_rule=alert.detection_rule,
            risk_score=alert.risk_score,
            created_at=alert.created_at,
            reviewed_by=alert.reviewed_by,
            review_notes=alert.review_notes,
            reviewed_at=alert.reviewed_at
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"알림 생성 중 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="알림 생성 중 오류가 발생했습니다"
        )

@router.get("/alerts", response_model=List[AMLAlertResponse])
async def get_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    player_id: Optional[str] = None,
    partner_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    AML 알림 목록을 조회합니다 (관리자 전용).
    """
    try:
        # Enum 변환
        status_enum = _convert_to_enum(status, AlertStatus, None) if status else None
        severity_enum = _convert_to_enum(severity, AlertSeverity, None) if severity else None
        
        aml_service = AMLService(db)
        alerts = await aml_service.get_alerts(
            partner_id=partner_id,
            player_id=player_id,
            status=status_enum,
            severity=severity_enum,
            start_date=start_date,
            end_date=end_date,
            offset=offset,
            limit=limit
        )
        
        # 응답 변환
        result = []
        for alert in alerts:
            result.append(AMLAlertResponse(
                id=alert.id,
                player_id=alert.player_id,
                alert_type=alert.alert_type,
                alert_severity=alert.alert_severity,
                alert_status=alert.alert_status,
                description=alert.description,
                detection_rule=alert.detection_rule or "unknown",
                risk_score=alert.risk_score,
                created_at=alert.created_at,
                reviewed_by=alert.reviewed_by,
                review_notes=alert.review_notes,
                reviewed_at=alert.reviewed_at
            ))
        
        return result
        
    except Exception as e:
        logger.error(f"알림 목록 조회 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # 빈 목록 반환 대신 500 에러 발생
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="알림 목록 조회 중 오류가 발생했습니다."
        )

@router.get("/alerts/{alert_id}", response_model=AMLAlertDetailResponse)
async def get_alert_detail(
    alert_id: int,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    AML 알림 상세 정보를 조회합니다 (관리자 전용).
    """
    aml_service = AMLService(db)
    
    try:
        # 서비스 계층을 통해 알림 조회
        alert = await aml_service.get_alert(alert_id) 
        if not alert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"알림 ID {alert_id}를 찾을 수 없습니다"
            )
        
        return AMLAlertDetailResponse(
            id=alert.id,
            player_id=alert.player_id,
            partner_id=alert.partner_id,
            transaction_id=alert.transaction_id,
            alert_type=alert.alert_type,
            alert_severity=alert.alert_severity,
            alert_status=alert.alert_status,
            description=alert.description,
            detection_rule=alert.detection_rule,
            risk_score=alert.risk_score,
            created_at=alert.created_at,
            reviewed_by=alert.reviewed_by,
            review_notes=alert.review_notes,
            reviewed_at=alert.reviewed_at,
            transaction_ids=alert.transaction_ids,
            transaction_details=alert.transaction_details,
            risk_factors=alert.risk_factors,
            alert_data=alert.alert_data,
            reported_at=alert.reported_at,
            report_reference=alert.report_reference,
            notes=alert.notes,
            updated_at=alert.updated_at
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"알림 상세 조회 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"알림 상세 조회 중 오류가 발생했습니다: {str(e)[:100]}"
        )

@router.put("/alerts/{alert_id}/status", response_model=AMLAlertResponse)
async def update_alert_status(
    alert_id: int,
    update_data: AlertStatusUpdate,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    AML 알림 상태를 업데이트합니다 (관리자 전용).
    """
    aml_service = AMLService(db)
    
    # alert_id 확인 및 설정
    update_data.alert_id = alert_id
    
    # 사용자 아이디 설정
    if not update_data.reviewed_by:
        update_data.reviewed_by = user.get("username") or user.get("id") or "admin"
    
    try:
        # 서비스 메소드가 async로 변경되었으므로 await 사용
        alert = await aml_service.update_alert_status(update_data)
        
        # 알림이 보고됨으로 변경된 경우, 이벤트 발행
        if update_data.status == AlertStatus.REPORTED:
            background_tasks.add_task(
                send_kafka_message,
                "aml_alert_reported",
                {
                    "alert_id": alert.id,
                    "player_id": alert.player_id,
                    "alert_type": str(alert.alert_type),
                    "severity": str(alert.alert_severity),
                    "risk_score": alert.risk_score,
                    "transaction_ids": alert.transaction_ids,
                    "reported_at": alert.reported_at.isoformat() if alert.reported_at else datetime.utcnow().isoformat(),
                    "report_reference": alert.report_reference,
                    "reviewed_by": alert.reviewed_by
                }
            )
        
        return AMLAlertResponse(
            id=alert.id,
            player_id=alert.player_id,
            alert_type=alert.alert_type,
            alert_severity=alert.alert_severity,
            alert_status=alert.alert_status,
            description=alert.description,
            detection_rule=alert.detection_rule,
            risk_score=alert.risk_score,
            created_at=alert.created_at,
            reviewed_by=alert.reviewed_by,
            review_notes=alert.review_notes,
            reviewed_at=alert.reviewed_at
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"알림 상태 업데이트 중 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="알림 상태 업데이트 중 오류가 발생했습니다"
        )

@router.get("/player/{player_id}/risk-profile", response_model=AMLRiskProfileResponse)
async def get_player_risk_profile(
    player_id: str,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    플레이어의 AML 위험 프로필을 조회합니다 (관리자 전용).
    """
    aml_service = AMLService(db)
    
    try:
        # 플레이어 위험 프로필 조회 (내부 메소드 대신 공개 메소드 사용)
        # _get_or_create_risk_profile 대신 get_player_risk_profile_public 호출
        risk_profile = await aml_service.get_player_risk_profile_public(player_id)
        
        if not risk_profile:
             raise HTTPException(
                 status_code=status.HTTP_404_NOT_FOUND,
                 detail=f"플레이어 ID {player_id}의 위험 프로필을 찾을 수 없습니다."
             )
        
        return AMLRiskProfileResponse(
            player_id=risk_profile.player_id,
            overall_risk_score=risk_profile.overall_risk_score,
            deposit_risk_score=risk_profile.deposit_risk_score,
            withdrawal_risk_score=risk_profile.withdrawal_risk_score,
            gameplay_risk_score=risk_profile.gameplay_risk_score,
            is_active=risk_profile.is_active,
            last_deposit_at=risk_profile.last_deposit_at,
            last_withdrawal_at=risk_profile.last_withdrawal_at,
            last_played_at=risk_profile.last_played_at,
            deposit_count_7d=risk_profile.deposit_count_7d,
            deposit_amount_7d=risk_profile.deposit_amount_7d,
            withdrawal_count_7d=risk_profile.withdrawal_count_7d,
            withdrawal_amount_7d=risk_profile.withdrawal_amount_7d,
            deposit_count_30d=risk_profile.deposit_count_30d,
            deposit_amount_30d=risk_profile.deposit_amount_30d,
            withdrawal_count_30d=risk_profile.withdrawal_count_30d,
            withdrawal_amount_30d=risk_profile.withdrawal_amount_30d,
            wager_to_deposit_ratio=risk_profile.wager_to_deposit_ratio,
            withdrawal_to_deposit_ratio=risk_profile.withdrawal_to_deposit_ratio,
            risk_factors=risk_profile.risk_factors,
            risk_mitigation=risk_profile.risk_mitigation,
            last_assessment_at=risk_profile.last_assessment_at
        )
    except Exception as e:
        logger.error(f"플레이어 위험 프로필 조회 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"플레이어 위험 프로필 조회 중 오류가 발생했습니다: {str(e)[:100]}"
        )

@router.get("/high-risk-players", response_model=List[AMLRiskProfileResponse])
async def get_high_risk_players(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    고위험 플레이어 목록을 조회합니다 (관리자 전용).
    """
    aml_service = AMLService(db)
    
    try:
        # 서비스 메소드가 async로 변경되었으므로 await 사용
        risk_profiles = await aml_service.get_high_risk_players(limit=limit, offset=offset)
        
        return [
            AMLRiskProfileResponse(
                player_id=profile.player_id,
                overall_risk_score=profile.overall_risk_score,
                deposit_risk_score=profile.deposit_risk_score,
                withdrawal_risk_score=profile.withdrawal_risk_score,
                gameplay_risk_score=profile.gameplay_risk_score,
                is_active=profile.is_active,
                last_deposit_at=profile.last_deposit_at,
                last_withdrawal_at=profile.last_withdrawal_at,
                last_played_at=profile.last_played_at,
                deposit_count_7d=profile.deposit_count_7d,
                deposit_amount_7d=profile.deposit_amount_7d,
                withdrawal_count_7d=profile.withdrawal_count_7d,
                withdrawal_amount_7d=profile.withdrawal_amount_7d,
                deposit_count_30d=profile.deposit_count_30d,
                deposit_amount_30d=profile.deposit_amount_30d,
                withdrawal_count_30d=profile.withdrawal_count_30d,
                withdrawal_amount_30d=profile.withdrawal_amount_30d,
                wager_to_deposit_ratio=profile.wager_to_deposit_ratio,
                withdrawal_to_deposit_ratio=profile.withdrawal_to_deposit_ratio,
                risk_factors=profile.risk_factors,
                risk_mitigation=profile.risk_mitigation,
                last_assessment_at=profile.last_assessment_at
            )
            for profile in risk_profiles
        ]
    except Exception as e:
        logger.error(f"고위험 플레이어 목록 조회 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # 빈 목록 반환 대신 500 에러 발생
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="고위험 플레이어 목록 조회 중 오류가 발생했습니다."
        )

@router.get("/player/{player_id}/alerts", response_model=List[AMLAlertResponse])
async def get_player_alerts(
    player_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    플레이어 관련 알림 목록을 조회합니다 (관리자 전용).
    """
    try:
        aml_service = AMLService(db)
        # 서비스 메소드가 async로 변경되었으므로 await 사용
        alerts = await aml_service.get_player_alerts(player_id=player_id, limit=limit, offset=offset)
        
        result = []
        for alert in alerts:
            result.append(AMLAlertResponse(
                id=alert.id,
                player_id=alert.player_id,
                alert_type=alert.alert_type,
                alert_severity=alert.alert_severity,
                alert_status=alert.alert_status,
                description=alert.description,
                detection_rule=alert.detection_rule or "unknown",
                risk_score=alert.risk_score,
                created_at=alert.created_at,
                reviewed_by=alert.reviewed_by,
                review_notes=alert.review_notes,
                reviewed_at=alert.reviewed_at
            ))
        
        return result
        
    except Exception as e:
        logger.error(f"플레이어 알림 목록 조회 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # 빈 목록 반환 대신 500 에러 발생
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="플레이어 알림 목록 조회 중 오류가 발생했습니다."
        )

@router.post("/report", response_model=AMLReportResponse)
async def create_aml_report(
    report_request: AMLReportRequest,
    background_tasks: BackgroundTasks,
    user: Dict[str, Any] = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """
    AML 보고서를 생성합니다 (관리자 전용).
    규제 기관에 제출하기 위한 보고서 (STR, CTR, SAR 등)
    """
    try:
        aml_service = AMLService(db)
        
        # 관련 알림 존재 확인 (서비스 내부에서 처리하도록 로직 이동 가능)
        # 여기서는 간단히 alert_id 를 서비스로 전달
        # if report_request.alert_id:
        #     alert = db.query(AMLAlert).filter(AMLAlert.id == report_request.alert_id).first()
        #     if not alert:
        #         raise HTTPException(
        #             status_code=status.HTTP_404_NOT_FOUND,
        #             detail=f"알림 ID {report_request.alert_id}를 찾을 수 없습니다"
        #         )
        
        # 보고서 생성 (내부 메소드 대신 공개 메소드 사용)
        # _create_aml_report 대신 create_report 호출
        report = await aml_service.create_report(
            report_request=report_request,
            created_by=user.get("username") or user.get("id") or "admin"
        )
        
        # 이벤트 발행 (Kafka)
        background_tasks.add_task(
            send_kafka_message,
            "aml_report_created",
            {
                "report_id": report.report_id,
                "player_id": report.player_id,
                "report_type": str(report.report_type),
                "jurisdiction": str(report.jurisdiction),
                "created_at": report.created_at.isoformat(),
                "alert_id": report.alert_id,
                "transaction_ids": report.transaction_ids,
                "notes": report.notes,
                "created_by": report.created_by
            }
        )
        
        return AMLReportResponse(
            report_id=report.report_id,
            player_id=report.player_id,
            report_type=report.report_type,
            jurisdiction=report.jurisdiction,
            created_at=report.created_at,
            status=report.status,
            submitted_at=report.submitted_at,
            submission_reference=report.submission_reference
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"보고서 생성 중 오류 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"보고서 생성 중 오류가 발생했습니다: {str(e)[:100]}"
        )