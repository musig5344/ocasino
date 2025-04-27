import secrets
from typing import List, Optional, Union, Dict, Any
from pydantic import AnyHttpUrl, field_validator, PostgresDsn, RedisDsn, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    """애플리케이션 설정"""
    
    # 기본 설정
    PROJECT_NAME: str = "B2B Casino Integration Platform"
    API_V1_PREFIX: str = "/api"
    DEBUG: bool = False
    VERSION: str = "1.0.0"
    LOG_LEVEL: str = "INFO"
    JSON_LOGS: bool = False # 추가: JSON 형식 로깅 활성화 여부
    LOG_FILE: str | None = None # 추가: 로그 파일 경로 설정
    PROJECT_DESCRIPTION: str = "API for B2B Online Casino Integration Platform"
    ENVIRONMENT: str = "dev" # 추가: 실행 환경 (dev, test, prod)
    MOUNT_STATIC_FILES: bool = False # 추가: 정적 파일 마운트 여부
    DEFAULT_RETURN_URL: str = "https://example.com/return" # 기본 반환 URL 추가
    
    # 보안 설정
    SECRET_KEY: str = secrets.token_urlsafe(32)
    REFRESH_TOKEN_SECRET_KEY: str = secrets.token_urlsafe(32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ENCRYPTION_KEY: Optional[str] = None # Fernet용 키
    AESGCM_KEY_B64: Optional[str] = None # AES-GCM용 키 (Base64 인코딩)
    
    # CORS 설정
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    
    @field_validator("BACKEND_CORS_ORIGINS", mode='before')
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    # 데이터베이스 설정
    DATABASE_URL: Optional[PostgresDsn] = None # 명시적 DATABASE_URL 필드 추가
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "casino_platform"
    POSTGRES_PORT: str = "5432"
    # SQLALCHEMY_DATABASE_URI는 DATABASE_URL 또는 개별 구성 요소로부터 파생되도록 함
    SQLALCHEMY_DATABASE_URI: Optional[PostgresDsn] = None
    
    # 테스트용 데이터베이스 URL (환경 변수 또는 .env.test 파일에서 로드)
    TEST_DATABASE_URL: Optional[PostgresDsn] = None
    
    @field_validator("SQLALCHEMY_DATABASE_URI", mode='before')
    def assemble_db_connection(cls, v: Optional[str], info: ValidationInfo) -> Any:
        # info.data에서 직접 DATABASE_URL 확인
        database_url_from_env = info.data.get("DATABASE_URL")
        if database_url_from_env:
            # print(f"[DEBUG Settings Validator] Using DATABASE_URL from env: {database_url_from_env}") # 디버깅용
            return database_url_from_env

        # 테스트 환경이고 TEST_DATABASE_URL이 설정된 경우
        is_test_environment = os.getenv("ENVIRONMENT") == "test"
        test_db_url_from_env = info.data.get("TEST_DATABASE_URL")
        if is_test_environment and test_db_url_from_env:
            # print(f"[DEBUG Settings Validator] Using TEST_DATABASE_URL from env: {test_db_url_from_env}") # 디버깅용
            return test_db_url_from_env
        
        # SQLALCHEMY_DATABASE_URI에 값이 직접 제공된 경우 (거의 사용 안 할 것으로 예상)
        if isinstance(v, str):
             # print(f"[DEBUG Settings Validator] Using provided SQLALCHEMY_DATABASE_URI: {v}") # 디버깅용
             return v

        # 위 조건에 모두 해당하지 않으면 개별 구성 요소로 조합 (기존 로직)
        # print("[DEBUG Settings Validator] Assembling URI from components.") # 디버깅용
        values = info.data
        user = values.get("POSTGRES_USER")
        password = values.get("POSTGRES_PASSWORD")
        host = values.get("POSTGRES_SERVER")
        port = values.get("POSTGRES_PORT")
        db_name = values.get("POSTGRES_DB")
        
        # 테스트 환경이면 DB 이름에 _test 추가 (선택적)
        if is_test_environment:
            db_name = f"{db_name}_test"
            
        # asyncpg 드라이버 사용 명시
        assembled_uri = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"
        # print(f"[DEBUG Settings Validator] Assembled URI: {assembled_uri}") # 디버깅용
        return assembled_uri
    
    # Redis 설정 (REDIS_URL 직접 사용)
    REDIS_URL: Optional[RedisDsn] = None # 변경: 개별 설정 대신 REDIS_URL 직접 사용
    # REDIS_HOST: str = "localhost"
    # REDIS_PORT: int = 6379
    # REDIS_DB: int = 0
    # REDIS_PASSWORD: Optional[str] = None
    # REDIS_URI: Optional[RedisDsn] = None # 제거
    
    # @validator("REDIS_URI", pre=True) # 제거
    # def assemble_redis_connection(cls, v: Optional[str], values: Dict[str, Any]) -> Any:
    #     if isinstance(v, str):
    #         return v
    #     
    #     password_part = f":{values.get('REDIS_PASSWORD')}@" if values.get("REDIS_PASSWORD") else ""
    #     
    #     return f"redis://{password_part}{values.get('REDIS_HOST')}:{values.get('REDIS_PORT')}/{values.get('REDIS_DB')}"
    
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
    AUTH_EXCLUDE_PATHS: List[str] = [  # 추가: 인증 제외 경로
        "/api/health",
        "/api/health/detailed",
        "/docs",
        "/redoc",
        "/openapi.json", # 기본값도 남겨둘 수 있음 (사용 안 하더라도)
        "/api/openapi.json", # 실제 사용 중인 경로 추가
        "/api/auth/token" # 인증 토큰 발급 경로는 제외
    ]
    
    # API 속도 제한 설정
    ENABLE_RATE_LIMITING: bool = True
    DEFAULT_RATE_LIMIT: int = 100  # 분당 요청 수
    RATE_LIMIT_STRATEGY: str = "fixed-window-elastic-expiry"  # 또는 "sliding-window"
    
    # 감사 로깅 설정
    AUDIT_LOG_ENABLED: bool = True
    AUDIT_LOG_INCLUDE_REQUEST_BODY: bool = True
    AUDIT_LOG_INCLUDE_RESPONSE_BODY: bool = False  # 응답 본문 로깅은 기본적으로 비활성화
    AUDIT_LOG_EXCLUDE_PATHS: List[str] = [  # 추가: 감사 로깅 제외 경로
        "/api/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/static/"
    ]
    
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
        extra = 'ignore' # 추가: .env 파일에 정의되지 않은 환경 변수 무시


def get_settings():
    """
    설정 싱글톤 인스턴스 가져오기
    
    Returns:
        Settings: 설정 객체
    """
    # 기본 .env 파일 로드 (선택적)
    # from dotenv import load_dotenv
    # load_dotenv()
    
    environment = os.getenv("ENVIRONMENT", "dev").lower()
    # print(f"[DEBUG] Environment detected: {environment}") # 디버깅 출력 제거
    env_file = f".env.{environment}" if environment != "prod" else ".env" # 환경별 .env 파일 지정
    # print(f"[DEBUG] Loading .env file: {env_file}") # 디버깅 출력 제거
    
    # Settings 객체 생성 시 환경 변수 및 .env 파일 로드
    settings = Settings(_env_file=env_file)
    # print(f"[DEBUG] Loaded REDIS_URL from settings: {settings.REDIS_URL}") # 디버깅 출력 제거
    
    # 테스트 환경일 경우 TEST_DATABASE_URL이 설정되었는지 확인 (선택적 경고)
    if environment == "test" and not settings.TEST_DATABASE_URL:
        # TEST_DATABASE_URL이 없는 경우, 기본 DB URL을 기반으로 생성 (예: DB 이름 변경)
        if settings.SQLALCHEMY_DATABASE_URI:
            # 주의: 이 방식은 SQLALCHEMY_DATABASE_URI validator가 TEST_DATABASE_URL을 반환하지 않을 때만 유효
            # validator가 이미 처리했다면 이 로직은 불필요
            base_uri = str(settings.SQLALCHEMY_DATABASE_URI).replace(f"/{settings.POSTGRES_DB}", f"/{settings.POSTGRES_DB}_test")
            settings.TEST_DATABASE_URL = base_uri # Pydantic 모델 필드 업데이트
            # print(f"Warning: TEST_DATABASE_URL not set. Using derived value: {settings.TEST_DATABASE_URL}") # 주석 처리 유지
        else:
            # print("Warning: TEST_DATABASE_URL is not set for the test environment.") # 주석 처리 유지
            pass # else 블록이 비어있지 않도록 pass 추가

    return settings


settings = get_settings()