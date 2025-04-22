import secrets
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseSettings, AnyHttpUrl, validator, PostgresDsn, RedisDsn
import os
from functools import lru_cache

class Settings(BaseSettings):
    """애플리케이션 설정"""
    
    # 기본 설정
    PROJECT_NAME: str = "B2B Casino Integration Platform"
    API_V1_PREFIX: str = "/api"
    DEBUG: bool = False
    VERSION: str = "1.0.0"
    
    # 보안 설정
    SECRET_KEY: str = secrets.token_urlsafe(32)
    REFRESH_TOKEN_SECRET_KEY: str = secrets.token_urlsafe(32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # CORS 설정
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    
    @validator("BACKEND_CORS_ORIGINS", pre=True)
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    # 데이터베이스 설정
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "casino_platform"
    POSTGRES_PORT: str = "5432"
    SQLALCHEMY_DATABASE_URI: Optional[PostgresDsn] = None
    
    @validator("SQLALCHEMY_DATABASE_URI", pre=True)
    def assemble_db_connection(cls, v: Optional[str], values: Dict[str, Any]) -> Any:
        if isinstance(v, str):
            return v
        
        return PostgresDsn.build(
            scheme="postgresql",
            user=values.get("POSTGRES_USER"),
            password=values.get("POSTGRES_PASSWORD"),
            host=values.get("POSTGRES_SERVER"),
            port=values.get("POSTGRES_PORT"),
            path=f"/{values.get('POSTGRES_DB') or ''}",
        )
    
    # Redis 설정
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_URI: Optional[RedisDsn] = None
    
    @validator("REDIS_URI", pre=True)
    def assemble_redis_connection(cls, v: Optional[str], values: Dict[str, Any]) -> Any:
        if isinstance(v, str):
            return v
        
        password_part = f":{values.get('REDIS_PASSWORD')}@" if values.get("REDIS_PASSWORD") else ""
        
        return f"redis://{password_part}{values.get('REDIS_HOST')}:{values.get('REDIS_PORT')}/{values.get('REDIS_DB')}"
    
    # Kafka 설정
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    
    # 서비스 도메인 설정
    DOMAIN_NAME: str = "api.casinoplatform.com"
    
    # 보안 관련 추가 설정
    SSL_ENABLED: bool = True
    
    # 비밀번호 정책
    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_REQUIRE_UPPERCASE: bool = True
    PASSWORD_REQUIRE_LOWERCASE: bool = True
    PASSWORD_REQUIRE_DIGITS: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = True
    
    # API 키 보안 설정
    ENABLE_API_HMAC: bool = True
    ENABLE_TIMESTAMP_VALIDATION: bool = True
    TIMESTAMP_MAX_DIFF: int = 300  # 5분 (초 단위)
    ENABLE_IP_WHITELIST: bool = True
    
    # API 속도 제한 설정
    ENABLE_RATE_LIMITING: bool = True
    DEFAULT_RATE_LIMIT: int = 100  # 분당 요청 수
    RATE_LIMIT_STRATEGY: str = "fixed-window-elastic-expiry"  # 또는 "sliding-window"
    
    # 감사 로깅 설정
    AUDIT_LOG_ENABLED: bool = True
    AUDIT_LOG_INCLUDE_REQUEST_BODY: bool = True
    AUDIT_LOG_INCLUDE_RESPONSE_BODY: bool = False  # 응답 본문 로깅은 기본적으로 비활성화
    
    # 키 만료 설정
    API_KEY_DEFAULT_EXPIRY_DAYS: int = 365  # 1년
    SESSION_TOKEN_EXPIRY_MINUTES: int = 60  # 1시간
    
    # 보고서 관련 설정
    REPORT_STORAGE_PATH: str = "/app/reports"
    MAX_REPORT_FILE_SIZE_MB: int = 100
    
    # 지갑 관련 설정
    MAX_TRANSACTION_AMOUNT: Dict[str, float] = {
        "USD": 100000.0,
        "EUR": 100000.0,
        "GBP": 100000.0,
        "KRW": 100000000.0,
        "JPY": 10000000.0,
        "DEFAULT": 100000.0
    }
    
    # AML 관련 설정
    AML_MONITORING_ENABLED: bool = True
    AML_ALERT_THRESHOLD: float = 10000.0  # USD 기준
    AML_HIGH_RISK_COUNTRIES: List[str] = [
        "AF", "BY", "BI", "CF", "CD", "KP", "ER", "IR", "IQ", "LY", 
        "ML", "MM", "NI", "PK", "RU", "SO", "SS", "SD", "SY", "VE", 
        "YE", "ZW"
    ]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """
    설정 싱글톤 인스턴스 가져오기
    
    Returns:
        Settings: 설정 객체
    """
    environment = os.getenv("ENVIRONMENT", "dev")
    settings = Settings(_env_file=f".env.{environment}")
    return settings


settings = get_settings()