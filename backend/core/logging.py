import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional
import uuid
import traceback
import inspect

class StructuredLogger:
    """구조화된 JSON 로깅을 위한 래퍼 클래스"""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name
    
    def _log(self, level: int, msg: str, **kwargs):
        """공통 로깅 로직"""
        # 호출자 정보 추출 (주의: 성능에 약간의 영향을 줄 수 있음)
        try:
            caller_frame = inspect.currentframe().f_back.f_back
            caller_info = inspect.getframeinfo(caller_frame)
            location = f"{caller_info.filename}:{caller_info.lineno}"
            function_name = caller_info.function
        except Exception: # Fallback if inspection fails
            location = "unknown"
            function_name = "unknown"

        # 기본 로그 구조
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z", # UTC 명시
            "level": logging.getLevelName(level),
            "message": msg,
            "logger": self.name,
            "location": location,
            "function": function_name
        }
        
        # 컨텍스트 정보 추가 (kwargs에서 직접 가져와서 위생 처리)
        context_data = {}
        reserved_keys = {"exception", "context", "request_id", "metadata", "duration_ms"}
        for key, value in kwargs.items():
             if key not in reserved_keys:
                  context_data[key] = value
        
        if kwargs.get("context"): # context 인자로 전달된 딕셔너리 병합
            context_data.update(kwargs["context"])

        if context_data:
            log_data["context"] = self._sanitize_data(context_data)
            
        # 요청 ID 추가 (있는 경우)
        if kwargs.get("request_id"):
            log_data["request_id"] = kwargs["request_id"]
        
        # 예외 정보 추가
        exception = kwargs.get("exception")
        if exception:
            log_data["exception"] = {
                "type": exception.__class__.__name__,
                "message": str(exception),
                # 오류 레벨 이상일 때만 트레이스백 포함 (선택적)
                "traceback": traceback.format_exc() if level >= logging.ERROR else None 
            }
        
        # 추가 메타데이터
        if kwargs.get("metadata"):
            log_data["metadata"] = self._sanitize_data(kwargs["metadata"]) # 메타데이터도 민감 정보 처리
            
        # 성능 측정 데이터
        if kwargs.get("duration_ms") is not None: # 0도 유효한 값이므로 None 체크
            log_data["performance"] = {
                "duration_ms": kwargs["duration_ms"]
            }
        
        # JSON 직렬화는 포맷터에 위임. extra 딕셔너리에 구조화된 데이터 전달
        self.logger.log(level, msg, extra={"structured": log_data})
    
    def _sanitize_data(self, data: Any) -> Any:
        """민감 정보 필터링 및 직렬화 불가능한 데이터 처리 (재귀적)"""
        sensitive_keys = {"password", "secret", "token", "key", "api_key", "credit_card", "authorization", "cookie"}
        max_list_items = 20 # 긴 리스트 로깅 방지
        max_string_length = 1024 # 긴 문자열 로깅 방지

        if isinstance(data, dict):
            clean_dict = {}
            for k, v in data.items():
                key_lower = str(k).lower()
                if any(sensitive in key_lower for sensitive in sensitive_keys):
                    clean_dict[k] = "***REDACTED***"
                else:
                    clean_dict[k] = self._sanitize_data(v)
            return clean_dict
        elif isinstance(data, list):
             # 리스트 길이 제한
            truncated = len(data) > max_list_items
            items_to_log = data[:max_list_items]
            sanitized_list = [self._sanitize_data(item) for item in items_to_log]
            if truncated:
                 sanitized_list.append(f"...<{len(data) - max_list_items} more items>...")
            return sanitized_list
        elif isinstance(data, str):
             # 문자열 길이 제한
            if len(data) > max_string_length:
                 return data[:max_string_length] + f"...<{len(data) - max_string_length} more chars>..."
            return data
        elif isinstance(data, (int, float, bool, type(None))):
            return data
        elif isinstance(data, (datetime, uuid.UUID)):
             # datetime, UUID는 문자열로 변환
            return str(data)
        else:
            # 직렬화 불가능한 타입 처리
            try:
                 # 기본 __str__ 또는 __repr__ 시도
                 return f"<unserializable: {type(data).__name__} - {str(data)}>"[:max_string_length] 
            except Exception:
                 return f"<unserializable: {type(data).__name__}>"
                
    def info(self, msg: str, **kwargs):
        self._log(logging.INFO, msg, **kwargs)
    
    def error(self, msg: str, exception: Optional[Exception] = None, **kwargs):
        # error 레벨에서는 항상 exception 정보를 포함하도록 함
        kwargs["exception"] = exception or kwargs.get("exception") 
        self._log(logging.ERROR, msg, **kwargs)
    
    def warning(self, msg: str, **kwargs):
        self._log(logging.WARNING, msg, **kwargs)
    
    def debug(self, msg: str, **kwargs):
        self._log(logging.DEBUG, msg, **kwargs)

class JsonFormatter(logging.Formatter):
    """JSON 형식의 로그 포맷터"""
    
    def format(self, record: logging.LogRecord) -> str:
        """LogRecord를 JSON 문자열로 포맷"""
        log_data = getattr(record, 'structured', None)
        
        if log_data and isinstance(log_data, dict):
            # 이미 StructuredLogger에서 생성된 구조화된 데이터를 사용
            # 필요시 추가 record 속성 병합 가능 (예: process, thread)
            log_data["process"] = record.process
            log_data["thread"] = record.threadName
        else:
            # 구조화된 데이터가 없는 경우 (예: 외부 라이브러리 로그)
            # 기본적인 구조로 변환
            log_data = {
                "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
                "level": record.levelname,
                "message": record.getMessage(), # 핸들러가 포맷팅하지 않도록 getMessage 사용
                "logger": record.name,
                "location": f"{record.pathname}:{record.lineno}",
                "function": record.funcName,
                "process": record.process,
                "thread": record.threadName
            }
            
            if record.exc_info:
                # 예외 정보 추가
                log_data["exception"] = {
                    "type": record.exc_info[0].__name__,
                    "message": str(record.exc_info[1]),
                    "traceback": self.formatException(record.exc_info) if record.levelno >= logging.ERROR else None
                }
            elif record.exc_text: # 예외 텍스트가 있는 경우
                 log_data["exception"] = {"message": record.exc_text}


        # 안전하게 JSON으로 직렬화
        try:
            return json.dumps(log_data, ensure_ascii=False, default=str)
        except TypeError as e:
            # 직렬화 실패 시 안전한 대체 문자열 반환
            fallback_message = f"Failed to serialize log record: {e}. Original message: {record.getMessage()}"
            fallback_log = {
                 "timestamp": datetime.utcnow().isoformat() + "Z",
                 "level": "ERROR",
                 "message": fallback_message,
                 "logger": "JsonFormatter.Error",
            }
            return json.dumps(fallback_log)

def configure_logging(
    log_level: str = "INFO",
    json_logs: bool = True,
    log_file: Optional[str] = None
):
    """애플리케이션 로깅 설정
    
    Args:
        log_level: 로그 레벨 문자열 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_logs: JSON 형식 로그 사용 여부
        log_file: 로그 파일 경로 (None이면 콘솔만 사용)
    """
    log_level_int = getattr(logging, log_level.upper(), logging.INFO)
    
    # 기존 핸들러 제거 (설정 중복 방지)
    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
         for handler in root_logger.handlers[:]:
              root_logger.removeHandler(handler)

    root_logger.setLevel(log_level_int)
    
    handlers: List[logging.Handler] = []
    
    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    handlers.append(console_handler)
    
    # 파일 핸들러 (지정된 경우)
    if log_file:
        try:
            # TODO: Consider RotatingFileHandler for production
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            handlers.append(file_handler)
        except Exception as e:
             # 파일 핸들러 생성 실패 시 콘솔에 경고 출력
             print(f"Warning: Could not create log file handler at {log_file}: {e}", file=sys.stderr)
    
    # 포맷터 설정
    if json_logs:
        formatter = JsonFormatter()
    else:
        # 기본 포맷터 (비-JSON)
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)-8s] %(name)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    # 모든 핸들러에 포맷터 적용 및 루트 로거에 추가
    for handler in handlers:
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    
    # 주요 라이브러리 로그 레벨 조정 (필요에 따라 변경)
    logging.getLogger("uvicorn.error").propagate = False # uvicorn 자체 핸들러 사용 방지
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    logging.info(f"Logging configured: level={log_level}, json_logs={json_logs}, file={log_file or 'None'}")

# 초기화 시 기본 로깅 구성 (선택적)
# configure_logging() 