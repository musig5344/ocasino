from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel
import logging

from backend.core.config import settings
from backend.core.security import verify_password, get_password_hash
from backend.db.database import get_db
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# OAuth2 비밀번호 스킴
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/token")

class TokenData(BaseModel):
    """토큰 데이터 모델"""
    partner_id: Optional[str] = None
    permissions: Optional[List[str]] = None
    exp: Optional[datetime] = None

class User(BaseModel):
    """사용자 모델"""
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None
    partner_id: Optional[str] = None
    permissions: Optional[Dict[str, List[str]]] = None

class UserInDB(User):
    """데이터베이스 사용자 모델"""
    hashed_password: str

def get_user(db: Session, username: str) -> Optional[UserInDB]:
    """
    사용자 정보 조회
    
    Args:
        db: 데이터베이스 세션
        username: 사용자 이름
        
    Returns:
        Optional[UserInDB]: 사용자 정보 또는 None
    """
    # 실제 구현에서는 데이터베이스에서 사용자 조회
    # 여기서는 예시로 하드코딩
    if username == "admin":
        return UserInDB(
            username="admin",
            email="admin@example.com",
            full_name="Admin User",
            disabled=False,
            partner_id="system",
            permissions={
                "partners": ["*"],
                "games": ["*"],
                "wallet": ["*"],
                "reports": ["*"]
            },
            hashed_password=get_password_hash("password")
        )
    
    return None

def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """
    사용자 인증
    
    Args:
        db: 데이터베이스 세션
        username: 사용자 이름
        password: 비밀번호
        
    Returns:
        Optional[User]: 인증된 사용자 정보 또는 None
    """
    user = get_user(db, username)
    if not user:
        return None
    
    if not verify_password(password, user.hashed_password):
        return None
    
    # 민감 정보 제거
    return User(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        disabled=user.disabled,
        partner_id=user.partner_id,
        permissions=user.permissions
    )

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    액세스 토큰 생성
    
    Args:
        data: 토큰에 포함할 데이터
        expires_delta: 만료 시간
        
    Returns:
        str: 생성된 액세스 토큰
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

def create_refresh_token(data: Dict[str, Any]) -> str:
    """
    리프레시 토큰 생성
    
    Args:
        data: 토큰에 포함할 데이터
        
    Returns:
        str: 생성된 리프레시 토큰
    """
    to_encode = data.copy()
    
    # 만료 시간 설정 (리프레시 토큰은 더 오래 유지)
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    # 만료 시간 추가
    to_encode.update({"exp": expire})
    
    # JWT 인코딩
    encoded_jwt = jwt.encode(
        to_encode,
        settings.REFRESH_TOKEN_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """
    현재 인증된 사용자 조회
    
    Args:
        token: JWT 토큰
        db: 데이터베이스 세션
        
    Returns:
        User: 인증된 사용자 정보
        
    Raises:
        HTTPException: 인증 실패
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # JWT 디코딩
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        # 사용자 이름 가져오기
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
        
        # 토큰 데이터 생성
        token_data = TokenData(
            partner_id=payload.get("partner_id"),
            permissions=payload.get("permissions"),
            exp=datetime.fromtimestamp(payload.get("exp"))
        )
    except JWTError:
        raise credentials_exception
    
    # 만료 여부 확인
    if token_data.exp < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 사용자 조회
    user = get_user(db, username)
    if user is None:
        raise credentials_exception
    
    # 비활성화 여부 확인
    if user.disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is disabled"
        )
    
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """
    현재 활성 사용자 조회
    
    Args:
        current_user: 현재 인증된 사용자
        
    Returns:
        User: 활성 사용자 정보
        
    Raises:
        HTTPException: 비활성 사용자
    """
    if current_user.disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is disabled"
        )
    
    return current_user

def has_permission(user: User, required_permission: str) -> bool:
    """
    사용자 권한 확인
    
    Args:
        user: 사용자 정보
        required_permission: 필요한 권한 (예: "wallet.read")
        
    Returns:
        bool: 권한 여부
    """
    if not user.permissions:
        return False
    
    # 권한 형식: "{resource}.{action}" 예: "wallet.read"
    parts = required_permission.split(".")
    if len(parts) != 2:
        return False
    
    resource, action = parts
    
    # 권한 확인 로직
    # 1. 정확한 리소스와 액션 일치 확인
    if resource in user.permissions and action in user.permissions[resource]:
        return True
    
    # 2. 리소스에 대한 모든 권한 확인 ("*" 액션)
    if resource in user.permissions and "*" in user.permissions[resource]:
        return True
    
    # 3. 모든 리소스에 대한 특정 액션 권한 확인
    if "*" in user.permissions and action in user.permissions["*"]:
        return True
    
    # 4. 모든 리소스에 대한 모든 액션 권한 확인 (슈퍼 관리자)
    if "*" in user.permissions and "*" in user.permissions["*"]:
        return True
    
    return False