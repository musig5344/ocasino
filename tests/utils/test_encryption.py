import os
import pytest
import base64
from decimal import Decimal
from unittest.mock import patch, MagicMock

from backend.utils.encryption import (
    encrypt_aes_gcm, decrypt_aes_gcm, 
    DataEncryptor, get_encryptor, _get_aes_gcm_key
)

# AES-GCM 테스트를 위한 픽스처
@pytest.fixture
def setup_aes_gcm_key():
    """AES-GCM 테스트를 위한 환경 설정"""
    # 32바이트(256비트) 키 생성
    original_key = os.getenv("AESGCM_KEY_B64")
    test_key = base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8')
    
    # 환경 변수 설정
    os.environ["AESGCM_KEY_B64"] = test_key
    
    yield test_key
    
    # 원래 상태로 복원
    if original_key:
        os.environ["AESGCM_KEY_B64"] = original_key
    else:
        # 키가 원래 없었다면 삭제
        if "AESGCM_KEY_B64" in os.environ:
             del os.environ["AESGCM_KEY_B64"]

# Fernet 테스트를 위한 픽스처
@pytest.fixture
def setup_fernet_key():
    """Fernet 테스트를 위한 환경 설정"""
    from cryptography.fernet import Fernet
    
    original_key = os.getenv("ENCRYPTION_KEY")
    test_key = Fernet.generate_key().decode()
    
    os.environ["ENCRYPTION_KEY"] = test_key
    
    yield test_key
    
    # 원래 상태로 복원
    if original_key:
        os.environ["ENCRYPTION_KEY"] = original_key
    else:
        # 키가 원래 없었다면 삭제
        if "ENCRYPTION_KEY" in os.environ:
            del os.environ["ENCRYPTION_KEY"]

# _get_aes_gcm_key 함수 직접 테스트
def test_get_aes_gcm_key_valid(setup_aes_gcm_key):
    """유효한 환경 변수가 설정되었을 때 키를 올바르게 가져오는지 테스트"""
    key = _get_aes_gcm_key()
    assert key is not None
    # base64 디코딩 후 32바이트인지 확인
    assert len(base64.urlsafe_b64decode(setup_aes_gcm_key)) == 32
    assert len(key) == 32

def test_get_aes_gcm_key_missing():
    """환경 변수가 없을 때 None을 반환하는지 테스트"""
    original_key = os.getenv("AESGCM_KEY_B64")
    if "AESGCM_KEY_B64" in os.environ:
        del os.environ["AESGCM_KEY_B64"]

    key = _get_aes_gcm_key()
    assert key is None

    # 원래 상태 복원 (테스트 실행 전 키가 있었다면)
    if original_key:
        os.environ["AESGCM_KEY_B64"] = original_key

def test_get_aes_gcm_key_invalid_length():
    """키 길이가 잘못되었을 때 None을 반환하는지 테스트"""
    original_key = os.getenv("AESGCM_KEY_B64")
    # 잘못된 길이의 키 설정 (32바이트가 아님)
    invalid_key_b64 = base64.urlsafe_b64encode(os.urandom(16)).decode('utf-8')
    os.environ["AESGCM_KEY_B64"] = invalid_key_b64

    key = _get_aes_gcm_key()
    assert key is None

    # 원래 상태 복원
    if original_key:
        os.environ["AESGCM_KEY_B64"] = original_key
    else:
        if "AESGCM_KEY_B64" in os.environ:
            del os.environ["AESGCM_KEY_B64"]


# AES-GCM 테스트
def test_aes_gcm_encryption_decryption(setup_aes_gcm_key):
    """AES-GCM 암호화 및 복호화 테스트"""
    original_data = "test-data-123"
    
    # 암호화
    encrypted = encrypt_aes_gcm(original_data)
    assert encrypted is not None
    # 암호화된 데이터는 원본과 달라야 함 (구체적인 형식은 구현에 따라 다름)
    assert encrypted != original_data 
    
    # 복호화
    decrypted = decrypt_aes_gcm(encrypted)
    assert decrypted == original_data

def test_aes_gcm_with_decimal(setup_aes_gcm_key):
    """Decimal 값 암호화 및 복호화 테스트"""
    original_amount = Decimal("123.45")
    
    # 암호화 (문자열로 변환 필요)
    encrypted = encrypt_aes_gcm(str(original_amount))
    assert encrypted is not None
    
    # 복호화 후 Decimal로 다시 변환
    decrypted = decrypt_aes_gcm(encrypted)
    assert decrypted is not None
    assert Decimal(decrypted) == original_amount

@patch('backend.utils.encryption._get_aes_gcm_key', return_value=None)
def test_aes_gcm_encrypt_invalid_key(mock_get_key):
    """유효하지 않은 키로 AES-GCM 암호화 시도 시 None 반환 테스트"""
    encrypted = encrypt_aes_gcm("some-data")
    assert encrypted is None
    mock_get_key.assert_called_once()

@patch('backend.utils.encryption._get_aes_gcm_key', return_value=None)
def test_aes_gcm_decrypt_invalid_key(mock_get_key):
    """유효하지 않은 키로 AES-GCM 복호화 시도 시 None 반환 테스트"""
    # 실제 암호화된 데이터 형식을 모방 (nonce + ciphertext + tag)
    # 이 값은 실제 암호화 결과가 아니며, 형식만 맞춘 임의의 값
    fake_encrypted_data = base64.urlsafe_b64encode(os.urandom(12 + 10 + 16)) 
    
    decrypted = decrypt_aes_gcm(fake_encrypted_data)
    assert decrypted is None
    mock_get_key.assert_called_once()

def test_aes_gcm_decrypt_tampered_data(setup_aes_gcm_key):
    """변조된 데이터 복호화 시도 시 None 또는 오류 발생 테스트"""
    original_data = "secure message"
    encrypted = encrypt_aes_gcm(original_data)
    
    # 데이터 변조 (마지막 바이트 변경)
    encrypted_bytes = base64.urlsafe_b64decode(encrypted)
    tampered_bytes = encrypted_bytes[:-1] + bytes([(encrypted_bytes[-1] + 1) % 256])
    tampered_encrypted = base64.urlsafe_b64encode(tampered_bytes)

    # 복호화 시도 시 None을 반환하거나 예외가 발생해야 함 (구현에 따라 다름)
    # 여기서는 None을 반환한다고 가정
    decrypted = decrypt_aes_gcm(tampered_encrypted)
    assert decrypted is None 
    # 또는 특정 예외를 기대한다면 pytest.raises 사용:
    # with pytest.raises(ValueError): # 혹은 다른 적절한 예외
    #     decrypt_aes_gcm(tampered_encrypted)


# DataEncryptor 테스트
def test_data_encryptor(setup_fernet_key):
    """DataEncryptor 클래스 테스트"""
    encryptor = DataEncryptor()
    
    original_data = "confidential-information"
    
    # 암호화
    encrypted = encryptor.encrypt(original_data)
    assert encrypted is not None
    # Fernet 암호화 결과는 bytes 타입
    assert isinstance(encrypted, bytes) 
    # 암호화된 데이터는 원본과 다름
    assert encrypted.decode('utf-8') != original_data 
    
    # 복호화
    decrypted = encryptor.decrypt(encrypted)
    assert decrypted == original_data

def test_get_encryptor_singleton(setup_fernet_key):
    """get_encryptor 싱글톤 패턴 테스트"""
    encryptor1 = get_encryptor()
    encryptor2 = get_encryptor()
    
    # 동일한 인스턴스인지 확인
    assert encryptor1 is encryptor2

def test_data_encryptor_different_keys(setup_fernet_key):
    """다른 키로 생성된 Encryptor는 데이터를 복호화할 수 없음"""
    from cryptography.fernet import Fernet

    encryptor1 = DataEncryptor() # setup_fernet_key 사용
    original_data = "test data"
    encrypted_by_1 = encryptor1.encrypt(original_data)

    # 다른 키 생성 및 설정
    new_key = Fernet.generate_key()
    with patch.dict(os.environ, {"ENCRYPTION_KEY": new_key.decode()}):
         # 새로운 키로 새 Encryptor 인스턴스 생성 (get_encryptor는 싱글톤이므로 직접 생성)
        encryptor2 = DataEncryptor() 

    # encryptor2로 encryptor1이 암호화한 데이터를 복호화 시도
    # 잘못된 키로 복호화 시도 시 decrypt 메서드는 None을 반환해야 함
    decrypted_by_2 = encryptor2.decrypt(encrypted_by_1)
    assert decrypted_by_2 is None
    
    # 기존 예외 발생 테스트 코드는 주석 처리
    # with pytest.raises(Exception): # cryptography.fernet.InvalidToken 예외 발생 예상
    #     encryptor2.decrypt(encrypted_by_1)

# 추가적인 테스트 케이스들 (필요시)
# - 빈 문자열 암호화/복호화
# - 매우 긴 데이터 암호화/복호화
# - 다른 인코딩의 데이터 처리 (utils/encryption.py 구현 확인 필요) 