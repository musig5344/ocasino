from typing import Optional, Dict, Any
import hashlib
import hmac
import base64
import secrets
import bcrypt
from datetime import datetime, timedelta
from passlib.context import CryptContext
import jwt
from jose import JWTError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from backend.core.config import settings
from backend.db.database import read_session_factory
from backend.core.exceptions import ValidationError

# 비밀번호 해싱을 위한 암호 컨텍스트
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 에러 임포트를 모듈 레벨로 이동
from backend.api.errors.exceptions import (
    ResourceNotFoundException, ForbiddenException, InvalidRequestException,
    InsufficientFundsException, DuplicateResourceException          
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    비밀번호 검증
    
    Args:
        plain_password: 평문 비밀번호
        hashed_password: 해시된 비밀번호
        
    Returns:
        bool: 검증 결과
    """
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """
    비밀번호 해싱
    
    Args:
        password: 평문 비밀번호
        
    Returns:
        str: 해시된 비밀번호
    """
    return pwd_context.hash(password)

def generate_api_key(length: int = 32) -> str:
    """
    API 키 생성
    
    Args:
        length: 키 길이 (바이트)
        
    Returns:
        str: 생성된 API 키
    """
    return secrets.token_hex(length)

def generate_api_secret(length: int = 32) -> str:
    """
    API 비밀 키 생성
    
    Args:
        length: 키 길이 (바이트)
        
    Returns:
        str: 생성된 API 비밀 키
    """
    return secrets.token_urlsafe(length)

async def get_api_key_secret(api_key: str) -> Optional[str]:
    """
    API 키에 대한 비밀 키 가져오기
    
    Args:
        api_key: API 키
        
    Returns:
        Optional[str]: 비밀 키 또는 None
    """
    # 함수 내부에서 AuthService 임포트
    from backend.services.auth.auth_service import AuthService
    
    # DB 세션 생성 (read_session_factory 사용)
    db = read_session_factory()
    
    try:
        # 인증 서비스 생성 (AuthService 사용)
        auth_service = AuthService(db)
        
        # API 키 정보 가져오기
        api_key_info = await auth_service.validate_api_key(api_key)
        if not api_key_info:
            return None
        
        # 비밀 키 반환 (AuthService 에서 반환하는 데이터 구조 확인 필요)
        return api_key_info.get("api_secret") # 예시: 실제 키 이름 확인 필요
    finally:
        await db.close()

def compute_hmac(
    api_key: str,
    secret: str,
    method: str,
    path: str,
    query_string: str,
    timestamp: str,
    body: Optional[bytes] = None
) -> str:
    """
    HMAC 서명 계산
    
    Args:
        api_key: API 키
        secret: 비밀 키
        method: HTTP 메소드
        path: 요청 경로
        query_string: 쿼리 문자열
        timestamp: 타임스탬프
        body: 요청 본문
        
    Returns:
        str: 계산된 HMAC 서명
    """
    # 서명 문자열 구성
    canonical_string = f"{method}\n{path}\n{query_string}\n{api_key}\n{timestamp}"
    
    # 본문이 있는 경우 해시하여 추가
    if body:
        body_hash = hashlib.sha256(body).hexdigest()
        canonical_string += f"\n{body_hash}"
    
    # HMAC 계산
    signature = hmac.new(
        secret.encode("utf-8"),
        canonical_string.encode("utf-8"),
        hashlib.sha256
    ).digest()
    
    # Base64 인코딩
    return base64.b64encode(signature).decode("utf-8")

async def verify_hmac(
    api_key: str,
    signature: str,
    method: str,
    path: str,
    query_string: str,
    timestamp: str,
    body: Optional[bytes] = None
) -> bool:
    """
    HMAC 서명 검증
    
    Args:
        api_key: API 키
        signature: 서명
        method: HTTP 메소드
        path: 요청 경로
        query_string: 쿼리 문자열
        timestamp: 타임스탬프
        body: 요청 본문
        
    Returns:
        bool: 검증 결과
    """
    # API 키에 대한 비밀 키 가져오기
    secret = await get_api_key_secret(api_key)
    if not secret:
        return False
    
    # HMAC 계산
    expected_signature = compute_hmac(
        api_key=api_key,
        secret=secret,
        method=method,
        path=path,
        query_string=query_string,
        timestamp=timestamp,
        body=body
    )
    
    # 타이밍 공격 방지를 위한 상수 시간 비교
    return hmac.compare_digest(signature, expected_signature)

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    JWT 액세스 토큰 생성
    
    Args:
        data: 토큰에 포함할 데이터
        expires_delta: 만료 시간
        
    Returns:
        str: 생성된 JWT 토큰
    """
    to_encode = data.copy()
    
    # 만료 시간 설정
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    # 만료 시간 추가
    to_encode.update({"exp": expire})
    
    # JWT 인코딩
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    
    return encoded_jwt

def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    JWT 액세스 토큰 검증
    
    Args:
        token: JWT 토큰
        
    Returns:
        Optional[Dict[str, Any]]: 토큰에 포함된 데이터 또는 None
    """
    try:
        # JWT 디코딩
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        return payload
    except JWTError:
        return None

def get_secure_random_string(length: int = 32) -> str:
    """
    안전한 랜덤 문자열 생성
    
    Args:
        length: 문자열 길이
        
    Returns:
        str: 생성된 문자열
    """
    return secrets.token_urlsafe(length)

# 비대칭 키 생성
def generate_key_pair():
    """RSA 키 쌍 (개인키, 공개키) 생성"""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    return private_pem, public_pem

# 비대칭 키를 사용한 JWT 생성
def create_rs256_token(
    data: dict, 
    private_key: bytes, 
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    RS256 알고리즘으로 JWT 생성
    
    Args:
        data: 토큰에 포함할 데이터
        private_key: PEM 형식의 RSA 개인 키
        expires_delta: 만료 시간 (timedelta)
        
    Returns:
        str: 생성된 JWT 토큰
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # 기본 만료 시간 (예: 설정에서 가져오기)
        default_expire_minutes = getattr(settings, 'RS256_TOKEN_EXPIRE_MINUTES', 15)
        expire = datetime.utcnow() + timedelta(minutes=default_expire_minutes)
    
    to_encode.update({"exp": expire})
    
    try:
        return jwt.encode(to_encode, private_key, algorithm="RS256")
    except Exception as e:
        # 로깅 추가 권장
        print(f"Error encoding RS256 token: {e}") 
        raise

# 비대칭 키를 사용한 JWT 검증
def verify_rs256_token(token: str, public_key: bytes) -> Optional[Dict[str, Any]]:
    """
    RS256 알고리즘으로 JWT 검증
    
    Args:
        token: 검증할 JWT 토큰
        public_key: PEM 형식의 RSA 공개 키
        
    Returns:
        Optional[Dict[str, Any]]: 디코딩된 페이로드 또는 None
    """
    try:
        return jwt.decode(token, public_key, algorithms=["RS256"])
    except jwt.PyJWTError as e:
        # 로깅 추가 권장
        print(f"Error verifying RS256 token: {e}")
        return None