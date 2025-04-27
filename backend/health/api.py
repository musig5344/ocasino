"""
헬스 체크 및 진단 API
시스템 상태 모니터링 및 진단
"""
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from typing import Dict, Any, List, Optional
import time
import platform
import asyncio
import os
import psutil # metrics.py 와 중복될 수 있으나, health check 용도로도 직접 사용
import uuid
import json # 진단 결과 로깅용
from datetime import datetime, timezone
from sqlalchemy import select

# Common Dependencies
from backend.core.dependencies import get_db, get_current_partner_id, get_current_permissions
# from backend.services.health.health_service import HealthService # Remove service import

# Common Schemas (Updated Import)
from backend.core.schemas import ErrorResponse, StandardResponse
# from backend.schemas.common import ErrorResponse # 이전 경로 주석 처리

# Health Specific Schemas
# Health Specific Schemas (Remove old incorrect import)
# from backend.schemas.health import (
#     HealthCheckResult, ServiceStatus, SystemStatus,
#     DiagnosticRequest, DiagnosticResult, HealthCheckResponse
# )
# Common Exceptions
from backend.core.exceptions import ServiceUnavailableException, PermissionDeniedError

# Schemas specific to this module (Keep this one)
# Schemas specific to this module
from backend.schemas.health import HealthCheckResponse # Correct schema name

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health & Diagnostics"]) # Prefix will be handled in api.py

# --- 기본 헬스 체크 --- 

@router.get(
    "/", 
    summary="기본 시스템 상태 확인", 
    description="시스템의 기본적인 가용성 및 버전, 환경 정보를 확인합니다. 로드 밸런서의 상태 확인(health check) 등에 사용될 수 있습니다.",
    response_model=Dict[str, str], # Explicitly define response model
    response_description="시스템의 기본 상태(ok), 버전, 환경 정보를 반환합니다.",
    responses={
        status.HTTP_200_OK: {
            "description": "시스템 정상 작동 중",
            "content": {
                "application/json": {
                    "example": {"status": "ok", "version": "1.2.3", "environment": "production"}
                }
            }
        }
    }
)
async def basic_health_check() -> Dict[str, str]: # Add return type hint
    """
    가장 기본적인 헬스 체크 엔드포인트입니다.
    성공 시 상태, 버전, 환경 정보를 포함한 JSON 응답을 반환합니다.
    """
    return {
        "status": "ok",
        "version": getattr(settings, 'VERSION', 'N/A'),
        "environment": getattr(settings, 'ENVIRONMENT', 'unknown')
    }

# --- 상세 헬스 체크 --- 

async def check_database_connectivity(db: AsyncSession) -> Dict[str, Any]:
    """데이터베이스 연결 및 간단한 쿼리 실행 확인"""
    start_time = time.perf_counter()
    try:
        # 매우 간단한 쿼리 실행 (테이블 접근 최소화)
        result = await db.execute("SELECT 1")
        await result.scalar()
        latency = time.perf_counter() - start_time
        return {
            "status": "ok",
            "latency_ms": round(latency * 1000, 2)
        }
    except Exception as e:
        latency = time.perf_counter() - start_time
        logger.error(f"Database health check failed: {e}", exc_info=False) # 스택 트레이스 제외 가능
        return {
            "status": "error",
            "message": f"Failed to connect or query: {str(e)[:100]}...", # 메시지 길이 제한
            "latency_ms": round(latency * 1000, 2) # 실패 시에도 latency 측정
        }

async def check_redis_connectivity() -> Dict[str, Any]:
    """Redis 연결 및 PING 테스트"""
    start_time = time.perf_counter()
    try:
        redis = await get_redis_client()
        if not redis:
            return {"status": "error", "message": "Redis client not available"}
        
        pong = await redis.ping()
        latency = time.perf_counter() - start_time
        if not pong:
            return {"status": "error", "message": "Redis PING failed", "latency_ms": round(latency * 1000, 2)}
        
        return {"status": "ok", "latency_ms": round(latency * 1000, 2)}
    except Exception as e:
        latency = time.perf_counter() - start_time
        logger.error(f"Redis health check failed: {e}", exc_info=False)
        return {"status": "error", "message": str(e)[:100]+"...", "latency_ms": round(latency * 1000, 2)}

# async def check_task_queue_status() -> Dict[str, Any]:
#     """백그라운드 작업 큐 상태 확인 (선택적)"""
#     try:
#         processor = get_task_processor()
#         return {
#             "status": "ok",
#             "queue_size": processor.queue.qsize(),
#             "active_workers": len([w for w in processor.workers if not w.done()])
#         }
#     except Exception as e:
#         logger.warning(f"Task queue check failed: {e}")
#         return {"status": "unavailable", "message": str(e)}

@router.get(
    "/detailed", 
    summary="상세 시스템 상태 확인", 
    response_model=Dict[str, Any], # Response model is a generic Dict
    description="""
    데이터베이스, 캐시 등 주요 시스템 컴포넌트의 연결 상태와 응답 시간을 확인하고, 간단한 시스템 메트릭 요약을 포함하여 반환합니다.
    각 컴포넌트의 상태는 `components` 필드 아래에 `ok` 또는 `error`로 표시됩니다.
    
    - 모든 주요 컴포넌트가 정상(`ok`)일 경우, 전체 상태(`overall_status`)는 `ok`가 되고 **200 OK**를 반환합니다.
    - 하나 이상의 컴포넌트에 오류(`error`)가 발생하면, 전체 상태는 `error`가 되고 **503 Service Unavailable**을 반환합니다.
    """,
    response_description="전체 상태, 버전, 환경, 확인 시각, 총 지연 시간, 각 컴포넌트 상태, 메트릭 요약을 포함한 상세 상태 정보를 반환합니다.",
    responses={
        status.HTTP_200_OK: {
            "description": "모든 주요 컴포넌트가 정상적으로 작동하고 있습니다.",
            "content": {
                "application/json": {
                    "example": {
                        "overall_status": "ok",
                        "version": "1.2.3",
                        "environment": "production",
                        "check_timestamp": 1678886400.123456,
                        "total_check_latency_ms": 150.75,
                        "components": {
                            "database": {"status": "ok", "latency_ms": 50.25},
                            "redis": {"status": "ok", "latency_ms": 10.5}
                        },
                        "metrics_summary": {
                            "last_collected_at": "2023-03-15T12:00:00Z", 
                            "cpu_percent": 15.5,
                            "memory_percent": 45.2
                        }
                    }
                }
            }
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "하나 이상의 주요 컴포넌트에 오류가 발생했습니다.",
            "content": {
                "application/json": {
                     "example": {
                        "overall_status": "error",
                        "version": "1.2.3",
                        "environment": "production",
                        "check_timestamp": 1678886405.654321,
                        "total_check_latency_ms": 550.10,
                        "components": {
                            "database": {"status": "ok", "latency_ms": 55.15},
                            "redis": {"status": "error", "message": "Connection refused", "latency_ms": 494.95}
                        },
                        "metrics_summary": {
                             "last_collected_at": "2023-03-15T12:00:05Z", 
                             "cpu_percent": 18.0,
                             "memory_percent": 46.0
                        }
                    }
                }
            }
        }
    }
)
async def detailed_health_check(
    db: AsyncSession = Depends(get_db) # Use standard DB dependency
): # Return type is implicitly Response or JSONResponse
    """
    주요 시스템 컴포넌트(데이터베이스, 캐시 등)의 상태를 확인합니다.
    전체 상태에 따라 200 OK 또는 503 Service Unavailable을 반환합니다.
    """
    start_time = time.perf_counter()
    
    # 병렬로 컴포넌트 상태 확인 실행
    db_check, redis_check = await asyncio.gather(
        check_database_connectivity(db),
        check_redis_connectivity(),
        # check_task_queue_status() # 작업 큐 확인 추가 시
    )
    
    components = {
        "database": db_check,
        "redis": redis_check,
        # "task_queue": task_queue_check # 작업 큐 확인 추가 시
    }
    
    # 전체 상태 결정
    overall_status = "ok"
    if any(comp.get("status") == "error" for comp in components.values()):
        overall_status = "error"
        
    # 시스템 메트릭 요약 추가 (기존 로직 유지)
    metrics_summary = {}
    try:
        metrics_collector = get_metrics_collector()
        latest_metrics = await metrics_collector.get_latest_metrics()
        if latest_metrics:
             metrics_summary = {
                 "last_collected_at": latest_metrics.get("timestamp"),
                 "cpu_percent": latest_metrics.get("system", {}).get("cpu_percent"),
                 "memory_percent": latest_metrics.get("process", {}).get("memory_percent")
             }
        else:
            metrics_summary = {"status": "unavailable", "message": "Metrics not yet collected"}
    except Exception as e:
        logger.warning(f"Failed to get metrics summary for health check: {e}")
        metrics_summary = {"status": "error", "message": f"Failed to retrieve metrics: {str(e)[:100]}..."}

    total_latency = time.perf_counter() - start_time
    http_status_code = status.HTTP_200_OK if overall_status == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE

    response_body = {
        "overall_status": overall_status,
        "version": getattr(settings, 'VERSION', 'N/A'),
        "environment": getattr(settings, 'ENVIRONMENT', 'unknown'),
        "check_timestamp": time.time(),
        "total_check_latency_ms": round(total_latency * 1000, 2),
        "components": components,
        "metrics_summary": metrics_summary
    }
    
    # 상태 코드와 함께 JSON 응답 반환
    from fastapi.responses import JSONResponse
    return JSONResponse(content=response_body, status_code=http_status_code)

# --- 시스템 진단 --- 

def _get_system_info():
    """ psutil을 이용한 시스템 정보 수집 (동기) """
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "boot_time": psutil.boot_time()
    }

def _get_resource_info():
    """ psutil을 이용한 리소스 정보 수집 (동기) """
    cpu_times = psutil.cpu_times_percent()
    virtual_mem = psutil.virtual_memory()
    swap_mem = psutil.swap_memory()
    disk_usage = psutil.disk_usage(os.path.abspath("/"))
    net_io = psutil.net_io_counters()

    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1), # 짧은 interval로 현재 사용량 측정
        "cpu_times_percent": {
            "user": cpu_times.user,
            "system": cpu_times.system,
            "idle": cpu_times.idle
        },
        "memory": {
            "total_gb": round(virtual_mem.total / (1024**3), 2),
            "available_gb": round(virtual_mem.available / (1024**3), 2),
            "used_gb": round(virtual_mem.used / (1024**3), 2),
            "percent_used": virtual_mem.percent
        },
        "swap": {
            "total_gb": round(swap_mem.total / (1024**3), 2),
            "used_gb": round(swap_mem.used / (1024**3), 2),
            "percent_used": swap_mem.percent
        },
        "disk": {
            "total_gb": round(disk_usage.total / (1024**3), 2),
            "used_gb": round(disk_usage.used / (1024**3), 2),
            "free_gb": round(disk_usage.free / (1024**3), 2),
            "percent_used": disk_usage.percent
        },
        "network": {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv,
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv
        }
    }

def _get_process_info():
    """ 현재 실행 중인 프로세스 정보 수집 (동기) """
    current_process = psutil.Process()
    return {
        "pid": current_process.pid,
        "name": current_process.name(),
        "status": current_process.status(),
        "username": current_process.username(),
        "create_time": current_process.create_time(),
        "cpu_percent": current_process.cpu_percent(interval=0.1),
        "memory_info": {
            "rss_mb": round(current_process.memory_info().rss / (1024**2), 2),
            "vms_mb": round(current_process.memory_info().vms / (1024**2), 2)
        },
        "memory_percent": current_process.memory_percent(),
        "num_threads": current_process.num_threads(),
        "open_files": len(current_process.open_files()),
        "connections": len(current_process.connections(kind='inet'))
    }

async def collect_and_log_diagnostics(trace_id: str):
    """시스템, 리소스, 프로세스 정보를 수집하여 JSON 형식으로 로깅 (비동기)"""
    logger.info(f"Starting diagnostics collection with trace_id: {trace_id}")
    start_time = time.time()
    diagnostics_data = {}
    try:
        # 각 정보 수집 함수를 비동기적으로 실행 (실제로는 동기 함수지만, 예시로 gather 사용)
        # psutil 함수들은 대부분 I/O bound 가 아니므로 asyncio 로 감싸도 큰 이득은 없지만,
        # 향후 다른 비동기 진단 작업 추가를 고려하여 패턴 유지
        system_info, resource_info, process_info = await asyncio.gather(
            asyncio.to_thread(_get_system_info), # 동기 함수를 비동기 스레드에서 실행
            asyncio.to_thread(_get_resource_info),
            asyncio.to_thread(_get_process_info)
        )
        
        diagnostics_data = {
            "trace_id": trace_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system": system_info,
            "resources": resource_info,
            "process": process_info
        }
        
        # JSON으로 직렬화하여 로그 기록 (pretty print는 선택 사항)
        log_message = json.dumps(diagnostics_data, indent=2, default=str) # datetime 등 직렬화 처리
        logger.info(f"Diagnostics data:\n{log_message}")
        
    except Exception as e:
        logger.exception(f"Error during diagnostics collection (trace_id: {trace_id}): {e}")
        diagnostics_data["error"] = str(e)
        log_message = json.dumps(diagnostics_data, indent=2, default=str)
        logger.error(f"Failed diagnostics data:\n{log_message}")
        
    finally:
        end_time = time.time()
        duration = end_time - start_time
        logger.info(f"Diagnostics collection finished in {duration:.2f} seconds (trace_id: {trace_id})")

@router.post(
    "/diagnostics", 
    summary="시스템 진단 정보 수집 요청 (관리자 전용)", 
    status_code=status.HTTP_202_ACCEPTED,
    description="""
    시스템의 상세 진단 정보(시스템 사양, 실시간 리소스 사용량, 현재 프로세스 정보 등) 수집을 **비동기적으로 요청**합니다.
    수집된 정보는 서버 로그(JSON 형식)에 기록되며, 문제 해결 및 시스템 분석에 활용될 수 있습니다.
    
    - 이 엔드포인트는 진단 정보 수집 *요청*이 성공적으로 접수되었는지 여부만 즉시 반환합니다.
    - 실제 정보 수집 및 로깅은 백그라운드에서 수행됩니다.
    - **주의:** 이 엔드포인트는 시스템 부하를 유발할 수 있으므로 필요한 경우에만 사용해야 합니다.
    
    **권한 요구사항:** `diagnostics.request` (또는 이에 준하는 관리자 권한)
    """,
    response_model=Dict[str, str], # Response model for the acceptance message
    response_description="진단 정보 수집 요청이 성공적으로 접수되었음을 나타내는 응답입니다. `trace_id`는 로그에서 해당 진단 결과를 찾는 데 사용됩니다.",
    responses={
        status.HTTP_202_ACCEPTED: {"description": "진단 정보 수집 요청 접수됨", "content": {"application/json": {"example": {"message": "Diagnostics collection requested", "trace_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef"}}}},
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": "인증되지 않은 접근"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "진단 요청 권한(`diagnostics.request`) 없음"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ErrorResponse, "description": "진단 요청 처리(백그라운드 작업 예약) 중 내부 오류 발생"}
    }
)
async def request_diagnostics(
    background_tasks: BackgroundTasks,
    requesting_permissions: List[str] = Depends(get_current_permissions) # Permission dependency
    # Explicit permission dependency can be added if using require_permission decorator/dependency
    # _: None = Depends(require_permission("diagnostics.request")) 
) -> Dict[str, str]: # Add return type hint
    """
    시스템 진단 정보 수집을 비동기적으로 요청합니다.
    관리자 권한(`diagnostics.request`)이 필요합니다.
    """
    # Check permission
    if "diagnostics.request" not in requesting_permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied: diagnostics.request required")
        
    trace_id = str(uuid.uuid4()) # 고유 추적 ID 생성
    
    try:
        # 백그라운드에서 진단 정보 수집 및 로깅 작업 예약
        background_tasks.add_task(collect_and_log_diagnostics, trace_id)
        
        logger.info(f"Diagnostics collection background task scheduled with trace_id: {trace_id}")
        return {"message": "Diagnostics collection requested", "trace_id": trace_id}
        
    except Exception as e:
        # 백그라운드 작업 예약 실패 시 (매우 드묾)
        logger.exception(f"Failed to schedule diagnostics collection task (trace_id: {trace_id}): {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Failed to schedule diagnostics collection"
        ) 

@router.get(
    "/health", 
    response_model=StandardResponse[HealthCheckResponse], 
    summary="서비스 상태 확인", 
    description="API 및 주요 의존성(예: 데이터베이스)의 현재 상태를 확인합니다.",
    tags=["System Health"],
    responses={
        status.HTTP_200_OK: {"description": "서비스 정상 작동 중"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "서비스 일부 또는 전체 이용 불가"}
    }
)
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    API 서버 및 주요 시스템 (DB 등) 상태를 확인합니다.
    """
    db_status = "ok"
    try:
        # Try a simple query to check DB connection
        await db.execute(select(1))
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "error"
        # Raise 503 if DB is down
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection failed"
        )

    response_data = HealthCheckResponse(
        status="ok", 
        timestamp=datetime.now(timezone.utc),
        dependencies=[
            {"name": "database", "status": db_status}
            # Add checks for other dependencies like Redis, Kafka if needed
        ]
    )
    return success_response(data=response_data, message="Service is healthy.") 