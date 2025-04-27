import os
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.backends import default_backend
import base64
import secrets
from typing import Optional, Union, Any
import logging

from backend.core.config import settings # 설정에서 키 로드

logger = logging.getLogger(__name__)

# --- AES-GCM 구현 ---

# 환경 변수 또는 설정에서 32바이트(256비트) 암호화 키 로드
# 보안상 Base64 인코딩된 키를 환경 변수에 저장하는 것이 일반적입니다.
# _ENCRYPTION_KEY = None # 초기화 -> 제거
# try:
#     # 설정 파일 (settings.ENCRYPTION_KEY) 에 Base64 인코딩된 키가 있다고 가정
#     encryption_key_setting = settings.ENCRYPTION_KEY
#     if encryption_key_setting:
#         _ENCRYPTION_KEY = base64.urlsafe_b64decode(encryption_key_setting)
#         if len(_ENCRYPTION_KEY) != 32:
#             logger.error("ENCRYPTION_KEY from settings must be a 32-byte (256-bit) key, base64 encoded.")
#             _ENCRYPTION_KEY = None # 키를 유효하지 않음으로 표시
#     else:
#         logger.warning("ENCRYPTION_KEY is not set in settings.")
# except AttributeError:
#     logger.warning("ENCRYPTION_KEY setting attribute is missing.")
# except (TypeError, ValueError) as e:
#      logger.error(f"Invalid ENCRYPTION_KEY format in settings: {e}. Ensure it's correctly base64 encoded.")
#      _ENCRYPTION_KEY = None # 키를 유효하지 않음으로 표시

# _ENCRYPTION_KEY 사용 전 None 체크 필요
# 예: if _ENCRYPTION_KEY is None: raise ValueError("Encryption key is not configured or invalid.")

def _get_aes_gcm_key() -> Optional[bytes]:
    """Retrieves the AES-GCM key from settings. Returns None if unavailable or invalid."""
    # Pydantic 설정을 통해 로드된 키 사용
    key_b64 = settings.AESGCM_KEY_B64 
    source = "settings.AESGCM_KEY_B64"
    
    # 설정에 없으면 os.getenv 시도 (Fallback, 권장하지 않음)
    if not key_b64:
        key_b64 = os.getenv("AESGCM_KEY_B64")
        source = "os.getenv('AESGCM_KEY_B64')"
        logger.warning("AESGCM_KEY_B64 not found in settings, falling back to os.getenv.")
        
    logger.debug(f"Read AESGCM_KEY_B64 from {source}: '{key_b64}'")
    if key_b64:
        try:
            # 키 값 앞뒤 공백 제거 추가
            key_bytes = base64.urlsafe_b64decode(key_b64.strip())
            logger.debug(f"Decoded key length: {len(key_bytes)} bytes")
            if len(key_bytes) == 32: # AES-256 key
                return key_bytes
            else:
                logger.error(f"AESGCM_KEY_B64 from {source} is not 32 bytes after base64 decoding.")
        except (TypeError, base64.binascii.Error) as e:
            logger.error(f"AESGCM_KEY_B64 ('{key_b64}') from {source} is not valid base64: {e}")
    
    logger.error("AESGCM_KEY_B64 is not set or invalid. AES-GCM operations will fail.") # 에러 레벨로 변경
    return None

def encrypt_aes_gcm(plaintext: str) -> Optional[str]:
    """AES-GCM을 사용하여 평문을 암호화합니다."""
    key = _get_aes_gcm_key()
    if not key or plaintext is None:
        logger.error("AES-GCM encryption skipped: Key missing or plaintext is None.")
        return None

    try:
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)  # 96-bit nonce recommended for AES-GCM
        plaintext_bytes = str(plaintext).encode('utf-8')
        ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, None)
        # Nonce + Ciphertext 를 base64 인코딩하여 반환
        encrypted_data = base64.urlsafe_b64encode(nonce + ciphertext)
        return encrypted_data.decode('utf-8')
    except ImportError:
        logger.error("cryptography library is required for AES-GCM but not installed.")
        return None
    except Exception as e:
        logger.exception(f"AES-GCM encryption failed: {e}")
        return None

def decrypt_aes_gcm(encrypted_data: Any) -> Optional[str]:
    """
    AES-GCM 암호화된 데이터를 복호화합니다.
    SQLAlchemy InstrumentedAttribute 등 다양한 입력 타입을 처리합니다.
    """
    key = _get_aes_gcm_key()
    if not key or encrypted_data is None:
        logger.error("AES-GCM decryption skipped: Key missing or encrypted_data is None.")
        return None

    try:
        # Handle potential SQLAlchemy InstrumentedAttribute or other non-string types
        # Propsoed change: Ensure input is treated as string
        if hasattr(encrypted_data, '__class__') and 'sqlalchemy' in str(type(encrypted_data)):
            # Specific handling for SQLAlchemy proxied attributes if needed, 
            # but often converting to string is sufficient if it holds the base64 data.
             encrypted_str = str(encrypted_data)
        elif not isinstance(encrypted_data, str):
             # Convert other non-string types to string
             encrypted_str = str(encrypted_data)
        else:
            encrypted_str = encrypted_data

        if not encrypted_str:
            logger.debug("decrypt_aes_gcm called with empty data after string conversion.")
            return None # Return None for empty string after potential conversion

        # Decode base64
        decoded_data = base64.urlsafe_b64decode(encrypted_str.encode('utf-8'))
        if len(decoded_data) < 13: # Must have at least 12 bytes nonce + 1 byte ciphertext
             raise ValueError("Invalid encrypted data length (too short).")
             
        nonce = decoded_data[:12]  # First 12 bytes are nonce
        ciphertext = decoded_data[12:]

        # Decrypt using AESGCM
        aesgcm = AESGCM(key)
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext_bytes.decode('utf-8')

    except (TypeError, ValueError, base64.binascii.Error) as e:
        # Log specific errors related to decoding/decryption structure
        logger.error(f"AES-GCM decryption failed for data '{str(encrypted_data)[:50]}...': {e}", exc_info=False) # Avoid logging full potentially sensitive data
        return None
    except ImportError:
        logger.error("cryptography library is required for AES-GCM decryption but not installed.")
        return None
    except Exception as e:
        # Catch unexpected errors during decryption
        logger.exception(f"Unexpected error during AES-GCM decryption: {e}")
        return None

# --- SQLAlchemy Type Decorator (선택적 대안) ---
# 만약 하이브리드 속성 대신 TypeDecorator를 사용하고 싶다면 아래와 같이 구현 가능
# from sqlalchemy import TypeDecorator, String
# class EncryptedString(TypeDecorator):
#     impl = String
#     cache_ok = True # 캐싱 가능 여부 (성능 관련)
#
#     def process_bind_param(self, value, dialect):
#         if value is not None:
#             return encrypt_aes_gcm(str(value))
#         return None
#
#     def process_result_value(self, value, dialect):
#         if value is not None:
#             try:
#                 return decrypt_aes_gcm(value)
#             except Exception as e:
#                 # 복호화 실패 처리
#                 print(f"Failed to decrypt value from DB: {e}")
#                 return None # 또는 에러 표시 문자열 반환
#         return None

# --- 참고: Fernet (더 간단한 인터페이스, AES128-CBC + HMAC 사용) ---
# try:
#     _FERNET_KEY = settings.ENCRYPTION_KEY # Fernet은 URL-safe base64 인코딩된 32바이트 키 필요
#     f = Fernet(_FERNET_KEY)
# except AttributeError:
#     raise ImportError("ENCRYPTION_KEY is not set in settings for Fernet.")
#
# def encrypt_fernet(plaintext: str) -> Optional[str]:
#     if plaintext is None: return None
#     return f.encrypt(str(plaintext).encode('utf-8')).decode('utf-8')
#
# def decrypt_fernet(token: str) -> Optional[str]:
#     if token is None: return None
#     try:
#         return f.decrypt(token.encode('utf-8')).decode('utf-8')
#     except InvalidToken:
#         print("Decryption failed with Fernet: Invalid token")
#         return None 

# 환경 변수에서 키를 읽어오거나, 없으면 에러 발생 -> DataEncryptor.__init__ 에서 처리하도록 변경
# ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
# if not ENCRYPTION_KEY:
#     error_msg = "CRITICAL: ENCRYPTION_KEY environment variable is not set. Application cannot encrypt/decrypt data."
#     logger.critical(error_msg)
#     raise ValueError(error_msg)

class DataEncryptor:
    """
    데이터 암호화 도구
    
    시스템의 민감한 정보를 암호화/복호화하는 기능 제공
    Fernet (AES128-CBC + HMAC) 사용
    """
    
    def __init__(self, key: Optional[str] = None):
        """
        암호화 도구 초기화
        
        Args:
            key: 암호화 키 (Base64 인코딩된 32바이트 키)
                 None이면 환경 변수 ENCRYPTION_KEY 사용
        """
        # key 인자가 없으면 __init__ 시점의 환경 변수에서 읽어옴
        effective_key = key if key else os.getenv("ENCRYPTION_KEY")
        
        if not effective_key:
             # 키가 여전히 없으면 에러 발생
             raise ValueError("Encryption key is missing. Pass it directly or set ENCRYPTION_KEY environment variable.")
        
        try:
            # Fernet 생성자는 Base64 인코딩된 키의 bytes 버전을 기대합니다.
            # 키 형식 자체의 유효성 검사는 Fernet 생성자가 수행합니다.
            self.cipher = Fernet(effective_key.encode('utf-8'))
        except (ValueError, TypeError) as e:
            # Fernet 생성자가 키 형식 오류를 발생시킬 수 있음
            logger.error(f"Failed to initialize Fernet cipher with the provided key: {e}")
            raise ValueError(f"Invalid encryption key format for Fernet: {e}") from e
        except Exception as e:
             # 예상치 못한 다른 초기화 오류 처리
             logger.error(f"Unexpected error initializing DataEncryptor: {e}")
             raise ValueError("Unexpected error initializing DataEncryptor") from e
    
    def encrypt(self, data: Union[str, bytes]) -> bytes: # Return bytes as Fernet encrypts to bytes
        """
        데이터 암호화
        
        Args:
            data: 암호화할 데이터 (문자열 또는 바이트)
            
        Returns:
            bytes: 암호화된 데이터 (URL-safe Base64 인코딩된 바이트)
        """
        if isinstance(data, str):
            data_bytes = data.encode('utf-8')
        else:
            data_bytes = data
        
        encrypted_bytes = self.cipher.encrypt(data_bytes)
        # return encrypted_bytes.decode('utf-8') # Don't decode, return bytes
        return encrypted_bytes
    
    def decrypt(self, encrypted_data: Union[str, bytes]) -> Optional[str]:
        """
        데이터 복호화
        
        Args:
            encrypted_data: 암호화된 데이터 (URL-safe Base64 인코딩된 문자열 또는 바이트)
            
        Returns:
            Optional[str]: 복호화된 문자열. 복호화 실패 시 None 반환.
        """
        if isinstance(encrypted_data, str):
            # If input is string, assume it's base64 encoded and encode back to bytes
            try:
                encrypted_bytes = encrypted_data.encode('utf-8')
            except Exception as e:
                 logger.error(f"Could not encode encrypted data string to bytes: {e}")
                 return None
        elif isinstance(encrypted_data, bytes):
             encrypted_bytes = encrypted_data
        else:
            logger.error(f"Invalid type for encrypted_data: {type(encrypted_data)}")
            return None
            
        try:
            decrypted_bytes = self.cipher.decrypt(encrypted_bytes)
            return decrypted_bytes.decode('utf-8')
        except InvalidToken:
            logger.error("Failed to decrypt data: Invalid token or key")
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred during decryption: {e}", exc_info=True)
            return None

# 싱글톤 인스턴스
_encryptor = None

def get_encryptor() -> DataEncryptor:
    """
    암호화 도구 싱글톤 인스턴스 가져오기
    
    Returns:
        DataEncryptor: 암호화 도구 인스턴스
    """
    global _encryptor
    if _encryptor is None:
        try:
            # 이제 get_encryptor 호출 시점의 환경 변수를 사용하여 초기화됨
            _encryptor = DataEncryptor() 
        except ValueError as e:
             # 초기화 실패 시 에러 로깅 및 프로그램 중단 또는 기본 동작 정의 필요
             logger.critical(f"Failed to initialize DataEncryptor: {e}")
             # 여기서는 에러를 다시 발생시켜 애플리케이션 시작을 중단시킬 수 있음
             raise RuntimeError("Could not initialize DataEncryptor due to missing or invalid key.") from e
    return _encryptor 