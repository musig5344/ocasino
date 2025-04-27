"""
시스템 메트릭 수집 유틸리티
성능 및 리소스 사용량 모니터링
"""
import time
import threading
import logging
from typing import Dict, Any, List, Optional
import psutil
import platform
import os
import asyncio

from backend.core.config import settings # 설정에서 수집 간격 등을 가져올 수 있음

logger = logging.getLogger(__name__)

class MetricsCollector:
    """
    시스템 메트릭 수집기
    
    시스템 및 애플리케이션 성능 데이터 수집 (비동기 환경 고려)
    """
    
    def __init__(self, collection_interval: Optional[int] = None):
        """
        메트릭 수집기 초기화
        
        Args:
            collection_interval: 메트릭 수집 간격 (초). None이면 설정 값 사용.
        """
        self.collection_interval = collection_interval or getattr(settings, 'METRICS_COLLECTION_INTERVAL', 60)
        self.metrics = {}
        self._lock = asyncio.Lock()
        self._collection_task = None
        self._running = False
    
    async def start(self):
        """메트릭 수집 시작 (비동기)"""
        if self._running:
            return
        
        self._running = True
        self._collection_task = asyncio.create_task(self._collector_loop())
        logger.info(f"Metrics collector started with interval {self.collection_interval}s")
    
    async def stop(self):
        """메트릭 수집 중지 (비동기)"""
        if not self._running or not self._collection_task:
            return
            
        self._running = False
        self._collection_task.cancel()
        try:
            await self._collection_task
        except asyncio.CancelledError:
            logger.info("Metrics collector task cancelled.")
        except Exception as e:
            logger.error(f"Error during metrics collector shutdown: {e}", exc_info=True)
        finally:
             self._collection_task = None
        logger.info("Metrics collector stopped")
    
    async def get_latest_metrics(self) -> Dict[str, Any]:
        """최신 메트릭 데이터 가져오기 (비동기 안전)"""
        async with self._lock:
            return self.metrics.copy()
    
    async def _collector_loop(self):
        """메트릭 수집 루프 (비동기)"""
        while self._running:
            try:
                collected_metrics = await asyncio.to_thread(self._collect_all_metrics)
                async with self._lock:
                    self.metrics = collected_metrics
                await asyncio.sleep(self.collection_interval)
            except asyncio.CancelledError:
                break # 정상 종료
            except Exception as e:
                logger.error(f"Error collecting metrics: {e}", exc_info=True)
                # 오류 발생 시 잠시 대기 후 계속
                await asyncio.sleep(min(self.collection_interval, 15))
    
    def _collect_all_metrics(self) -> Dict[str, Any]:
        """동기적으로 모든 메트릭 수집 (to_thread에서 실행됨)"""
        # psutil 호출은 I/O 바운드이거나 CPU 바운드일 수 있으므로
        # asyncio.to_thread를 사용하는 것이 안전합니다.
        return {
            "timestamp": time.time(),
            "system": self._collect_system_metrics(),
            "process": self._collect_process_metrics(),
            "memory": self._collect_memory_metrics(),
            "disk": self._collect_disk_metrics(),
            "network": self._collect_network_metrics()
        }

    def _collect_system_metrics(self) -> Dict[str, Any]:
        """시스템 메트릭 수집"""
        try:
            load_avg = os.getloadavg() if hasattr(os, "getloadavg") else None
            boot_time = psutil.boot_time()
            return {
                "cpu_percent": psutil.cpu_percent(interval=0.1), # 짧은 간격으로 변경
                "cpu_count_logical": psutil.cpu_count(logical=True),
                "cpu_count_physical": psutil.cpu_count(logical=False),
                "load_avg_1m": load_avg[0] if load_avg else None,
                "load_avg_5m": load_avg[1] if load_avg else None,
                "load_avg_15m": load_avg[2] if load_avg else None,
                "boot_timestamp": boot_time,
                "uptime_seconds": time.time() - boot_time
            }
        except Exception as e:
             logger.warning(f"Could not collect system metrics: {e}")
             return {"error": str(e)}
    
    def _collect_process_metrics(self) -> Dict[str, Any]:
        """현재 프로세스 메트릭 수집"""
        try:
            process = psutil.Process()
            with process.oneshot(): # 효율성을 위해 여러 정보 한 번에 조회
                return {
                    "pid": process.pid,
                    "cpu_percent": process.cpu_percent(interval=0.1),
                    "memory_rss_bytes": process.memory_info().rss,
                    "memory_vms_bytes": process.memory_info().vms,
                    "memory_percent": process.memory_percent(),
                    "threads_count": process.num_threads(),
                    "open_files_count": len(process.open_files()) if hasattr(process, 'open_files') else None,
                    "connections_count": len(process.connections()) if hasattr(process, 'connections') else None,
                    "start_timestamp": process.create_time(),
                    "uptime_seconds": time.time() - process.create_time()
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
             logger.warning(f"Could not collect process metrics: {e}")
             return {"error": str(e)}
        except Exception as e:
             logger.error(f"Unexpected error collecting process metrics: {e}", exc_info=True)
             return {"error": str(e)}

    def _collect_memory_metrics(self) -> Dict[str, Any]:
        """시스템 메모리 메트릭 수집"""
        try:
            vm = psutil.virtual_memory()
            sm = psutil.swap_memory()
            return {
                "virtual": dict(vm._asdict()),
                "swap": dict(sm._asdict())
            }
        except Exception as e:
             logger.warning(f"Could not collect memory metrics: {e}")
             return {"error": str(e)}
    
    def _collect_disk_metrics(self) -> Dict[str, Any]:
        """디스크 메트릭 수집 (루트 파티션 기준)"""
        # TODO: 여러 파티션 지원 또는 설정 기반 경로 지원 추가 가능
        try:
            disk_usage = psutil.disk_usage("/")
            disk_io = psutil.disk_io_counters()
            return {
                "usage_root": dict(disk_usage._asdict()),
                "io": dict(disk_io._asdict()) if disk_io else None
            }
        except Exception as e:
             logger.warning(f"Could not collect disk metrics: {e}")
             return {"error": str(e)}
    
    def _collect_network_metrics(self) -> Dict[str, Any]:
        """네트워크 IO 메트릭 수집"""
        try:
            net_io = psutil.net_io_counters()
            return dict(net_io._asdict()) if net_io else {}
        except Exception as e:
             logger.warning(f"Could not collect network metrics: {e}")
             return {"error": str(e)}

# 싱글톤 인스턴스
_metrics_collector = None

def get_metrics_collector() -> MetricsCollector:
    """
    메트릭 수집기 싱글톤 인스턴스 가져오기
    
    Returns:
        MetricsCollector: 메트릭 수집기 인스턴스
    """
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector

async def startup_metrics_collector():
    """애플리케이션 시작 시 메트릭 수집기 시작"""
    collector = get_metrics_collector()
    await collector.start()

async def shutdown_metrics_collector():
    """애플리케이션 종료 시 메트릭 수집기 중지"""
    collector = get_metrics_collector()
    await collector.stop() 