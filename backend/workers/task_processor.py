"""
비동기 작업 처리기
확장성 있는 백그라운드 작업 처리
"""
import asyncio
from typing import Dict, Any, Callable, Awaitable
import logging

logger = logging.getLogger(__name__)

class TaskProcessor:
    """작업 큐와 비동기 워커 관리"""
    
    def __init__(self, worker_count: int = 5):
        self.queue = asyncio.Queue()
        self.worker_count = worker_count
        self.workers = []
        self.running = False
    
    async def start(self):
        """워커 시작"""
        self.running = True
        for i in range(self.worker_count):
            worker = asyncio.create_task(self._worker_loop(i))
            self.workers.append(worker)
        logger.info(f"Started {self.worker_count} task workers")
    
    async def stop(self):
        """워커 중지"""
        self.running = False
        for worker in self.workers:
            worker.cancel()
        self.workers = []
        logger.info("Task workers stopped")
    
    async def add_task(self, func: Callable, *args, **kwargs):
        """작업 추가"""
        await self.queue.put((func, args, kwargs))
    
    async def _worker_loop(self, worker_id: int):
        """워커 루프"""
        logger.info(f"Worker {worker_id} started")
        while self.running:
            try:
                func, args, kwargs = await self.queue.get()
                try:
                    if asyncio.iscoroutinefunction(func):
                        await func(*args, **kwargs)
                    else:
                        # 동기 함수는 별도 스레드에서 실행
                        await asyncio.to_thread(func, *args, **kwargs)
                except Exception as e:
                    logger.error(f"Error processing task in worker {worker_id}: {e}", exc_info=True)
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id} received cancellation signal.")
                break
            except Exception as e:
                logger.error(f"Unexpected error in worker {worker_id} loop: {e}", exc_info=True)
        logger.info(f"Worker {worker_id} stopped")

# 싱글톤 인스턴스
_task_processor = None

def get_task_processor() -> TaskProcessor:
    """작업 처리기 싱글톤 인스턴스 반환"""
    global _task_processor
    if _task_processor is None:
        # TODO: 설정에서 워커 수를 가져오도록 수정
        _task_processor = TaskProcessor(worker_count=settings.TASK_WORKER_COUNT if hasattr(settings, 'TASK_WORKER_COUNT') else 5) 
    return _task_processor

async def startup_task_processor():
    """애플리케이션 시작 시 작업 처리기 시작"""
    processor = get_task_processor()
    await processor.start()

async def shutdown_task_processor():
    """애플리케이션 종료 시 작업 처리기 중지"""
    processor = get_task_processor()
    await processor.stop() 