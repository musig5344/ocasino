"""
애플리케이션 공통 예외 클래스 정의
"""
from typing import Optional, Any

class AppException(Exception):
    """애플리케이션 기본 예외 클래스"""
    def __init__(self, message: str = "An application error occurred", status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class NotFoundError(AppException):
    """리소스를 찾을 수 없을 때 발생하는 범용 예외"""
    def __init__(self, resource_type: str = "Resource", identifier: Any = None, status_code: int = 404):
        if identifier:
            message = f"{resource_type} with identifier '{identifier}' not found."
        else:
            message = f"{resource_type} not found."
        super().__init__(message, status_code)
        self.resource_type = resource_type
        self.identifier = identifier

class AuthenticationError(AppException):
    """인증 실패 예외"""
    def __init__(self, message: str = "Authentication failed", status_code: int = 401):
        super().__init__(message, status_code)

class AuthorizationError(AppException):
    """권한 없음 예외"""
    def __init__(self, message: str = "Permission denied", status_code: int = 403):
        super().__init__(message, status_code)

class InvalidCredentialsError(AuthenticationError):
    """잘못된 자격 증명 예외"""
    def __init__(self, message: str = "Invalid credentials provided", status_code: int = 401):
        super().__init__(message, status_code)

class NotAllowedIPError(AuthorizationError):
    """허용되지 않은 IP 예외"""
    def __init__(self, ip_address: str, message: Optional[str] = None, status_code: int = 403):
        if message is None:
            message = f"IP address {ip_address} is not allowed."
        super().__init__(message, status_code)
        self.ip_address = ip_address

class PermissionDeniedError(AuthorizationError):
    """특정 작업에 대한 권한 부족 예외"""
    def __init__(self, permission: str, message: Optional[str] = None, status_code: int = 403):
        if message is None:
            message = f"Permission denied for action requiring: {permission}"
        super().__init__(message, status_code)
        self.permission = permission

# 추가적인 예외 클래스들...
class PartnerNotFoundError(AppException):
    def __init__(self, partner_id: Any = None, status_code: int = 404):
        message = f"Partner with ID {partner_id} not found" if partner_id else "Partner not found"
        super().__init__(message, status_code)

class APIKeyNotFoundError(AppException):
     def __init__(self, api_key: str = None, status_code: int = 404):
         message = f"API Key starting with {api_key[:8]}... not found or inactive" if api_key else "API Key not found"
         super().__init__(message, status_code)

class PartnerAlreadyExistsError(AppException):
     def __init__(self, partner_code: str, status_code: int = 409):
         message = f"Partner with code {partner_code} already exists."
         super().__init__(message, status_code)
         
class APIKeyGenerationError(AppException):
     def __init__(self, message: str = "Failed to generate a unique API key", status_code: int = 500):
         super().__init__(message, status_code)
         
class InvalidInputError(AppException):
     def __init__(self, message: str = "Invalid input provided", status_code: int = 400):
         super().__init__(message, status_code)

class DatabaseError(AppException):
     def __init__(self, message: str = "A database error occurred", status_code: int = 500):
         super().__init__(message, status_code)

# Wallet / Transaction related errors
class InsufficientFundsError(AppException):
    """잔액 부족 예외"""
    def __init__(self, player_id: Any, requested_amount: Any, current_balance: Any, status_code: int = 400):
        message = (
            f"Insufficient funds for player {player_id}. "
            f"Requested: {requested_amount}, Available: {current_balance}."
        )
        super().__init__(message, status_code)
        self.player_id = player_id
        self.requested_amount = requested_amount
        self.current_balance = current_balance

class WalletNotFoundError(AppException):
    """지갑을 찾을 수 없음 예외"""
    def __init__(self, player_id: Any = None, partner_id: Any = None, status_code: int = 404):
        if player_id and partner_id:
            message = f"Wallet not found for player {player_id} and partner {partner_id}"
        elif player_id:
            message = f"Wallet not found for player {player_id}"
        else:
            message = "Wallet not found"
        super().__init__(message, status_code)

class TransactionNotFoundError(AppException):
    """트랜잭션을 찾을 수 없음 예외"""
    def __init__(self, transaction_id: Any = None, reference_id: Any = None, status_code: int = 404):
        if transaction_id:
            message = f"Transaction with ID {transaction_id} not found"
        elif reference_id:
            message = f"Transaction with reference ID {reference_id} not found"
        else:
            message = "Transaction not found"
        super().__init__(message, status_code)

class DuplicateTransactionError(AppException):
    """중복 트랜잭션 예외 (예: 동일한 reference_id 사용)"""
    def __init__(self, reference_id: str, status_code: int = 409):
        message = f"Duplicate transaction: reference ID {reference_id} already exists."
        super().__init__(message, status_code)
        self.reference_id = reference_id

class InvalidTransactionStatusError(AppException):
    """잘못된 트랜잭션 상태 예외 (예: 이미 롤백된 트랜잭션 롤백 시도)"""
    def __init__(self, transaction_id: Any, current_status: str, expected_status: Optional[str] = None, status_code: int = 400):
        if expected_status:
            message = f"Invalid status for transaction {transaction_id}. Current: {current_status}, Expected: {expected_status}."
        else:
            message = f"Invalid status for transaction {transaction_id}: {current_status}."
        super().__init__(message, status_code)
        self.transaction_id = transaction_id
        self.current_status = current_status

class WalletLockedError(AppException):
    """잠긴 지갑 예외"""
    def __init__(self, player_id: Any, status_code: int = 403):
        message = f"Wallet for player {player_id} is locked."
        super().__init__(message, status_code)

class CurrencyMismatchError(AppException):
    """통화 불일치 예외"""
    def __init__(self, expected_currency: str, actual_currency: str, status_code: int = 400):
        message = f"Currency mismatch. Expected: {expected_currency}, Actual: {actual_currency}."
        super().__init__(message, status_code)
        self.expected_currency = expected_currency
        self.actual_currency = actual_currency

class InvalidAmountError(AppException):
    """유효하지 않은 금액 예외 (예: 0 또는 음수 금액)"""
    def __init__(self, amount: Any, message: Optional[str] = None, status_code: int = 400):
        if message is None:
            message = f"Invalid amount provided: {amount}. Amount must be positive."
        super().__init__(message, status_code)
        self.amount = amount

class ValidationError(AppException):
    """유효성 검사 실패 예외 (Pydantic 등)"""
    def __init__(self, detail: Any, status_code: int = 422):
        message = "Validation Error"
        super().__init__(message, status_code)
        self.detail = detail # Pydantic 에러 등의 상세 정보 

class ConflictError(AppException):
    """리소스 충돌 예외 (예: 고유해야 하는 값이 이미 존재)"""
    def __init__(self, resource_type: str = "Resource", identifier: Optional[str] = None, status_code: int = 409):
        if identifier:
            message = f"{resource_type} with identifier '{identifier}' already exists or causes a conflict."
        else:
            message = f"A conflict occurred with the requested {resource_type.lower()}.".capitalize()
        super().__init__(message, status_code)
        self.resource_type = resource_type
        self.identifier = identifier

class GameNotFoundError(AppException):
    """게임을 찾을 수 없을 때 발생하는 예외"""
    def __init__(self, game_id: Any = None, status_code: int = 404):
        message = f"Game with ID {game_id} not found" if game_id else "Game not found"
        super().__init__(message, status_code)
        self.game_id = game_id

class ProviderIntegrationError(AppException):
    """게임 제공사 연동 오류"""
    def __init__(self, message: str = "Game provider integration error", status_code: int = 503):
        super().__init__(message, status_code)

class DuplicateGameSessionError(AppException):
    """중복된 게임 세션 예외 (예: 동일 플레이어의 활성 세션 존재)"""
    def __init__(self, player_id: Any, game_id: Any, status_code: int = 409):
        message = f"Duplicate active game session found for player {player_id} and game {game_id}."
        super().__init__(message, status_code)
        self.player_id = player_id
        self.game_id = game_id

class GameSessionNotFoundError(AppException):
    """게임 세션을 찾을 수 없을 때 발생하는 예외"""
    def __init__(self, session_id: Any = None, status_code: int = 404):
        message = f"Game session with ID {session_id} not found" if session_id else "Game session not found"
        super().__init__(message, status_code)
        self.session_id = session_id

class InsufficientBalanceError(AppException):
    """잔액이 부족할 때 발생하는 예외"""
    status_code = 400
    error_code = "INSUFFICIENT_BALANCE"
    message = "계좌 잔액이 부족합니다."
    def __init__(self, player_id: Any = None, requested: Any = None, available: Any = None, message: Optional[str] = None):
        # Allow dynamic message generation if details are provided
        final_message = message if message else self.message
        if player_id and requested is not None and available is not None:
             final_message = f"Insufficient balance for player {player_id}. Requested: {requested}, Available: {available}."
        super().__init__(final_message, self.status_code)
        # Store details if provided
        self.player_id = player_id
        self.requested = requested
        self.available = available

# Add WalletOperationError
class WalletOperationError(AppException):
    """지갑 작업 중 일반 오류"""
    def __init__(self, message: str = "Wallet operation failed", status_code: int = 500):
        super().__init__(message, status_code) 

class ServiceUnavailableException(AppException):
    """서비스 이용 불가 예외 (예: 외부 시스템 장애, 점검)"""
    def __init__(self, service_name: str = "Service", message: Optional[str] = None, status_code: int = 503):
        if message is None:
            message = f"{service_name} is temporarily unavailable. Please try again later."
        super().__init__(message, status_code)
        self.service_name = service_name 

class BusinessLogicError(AppException):
    """비즈니스 로직 오류 예외"""
    def __init__(self, message: str = "Business logic error occurred", status_code: int = 400):
        super().__init__(message, status_code) 