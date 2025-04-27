import uuid
from sqlalchemy.types import TypeDecorator, CHAR, Text, String as DBString, VARCHAR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
import logging
import ipaddress # Add import for ipaddress module

logger = logging.getLogger(__name__)

class UUIDType(TypeDecorator):
    """
    플랫폼 독립적인 UUID 타입.

    PostgreSQL에서는 네이티브 UUID 타입을 사용하고,
    다른 데이터베이스(예: SQLite)에서는 CHAR(32)로 저장합니다.
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            # PostgreSQL에서는 네이티브 UUID 타입 사용
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        elif dialect.name == 'sqlite':
            return dialect.type_descriptor(VARCHAR(32))
        else:
            # 다른 DB에서는 CHAR(32) 사용
            return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            # PostgreSQL에서는 UUID 객체 그대로 전달
            return value if isinstance(value, uuid.UUID) else str(value)
        elif dialect.name == 'sqlite':
            # SQLite stores as string
            return str(value)
        else:
            # 다른 DB에서는 문자열로 변환하여 저장
            if not isinstance(value, uuid.UUID):
                try:
                    return uuid.UUID(value).hex # 입력이 문자열일 경우
                except ValueError:
                     logger.error(f"Invalid UUID format for bind parameter: {value}")
                     raise ValueError(f"Invalid UUID format: {value}") from None
            # UUID 객체인 경우 hex 문자열로 변환
            return value.hex

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            # PostgreSQL에서는 이미 UUID 객체로 반환됨 (as_uuid=True 설정 시)
            # 만약 as_uuid=False 라면 여기서 uuid.UUID(value) 변환 필요
            if isinstance(value, uuid.UUID):
                 return value
            else:
                 # 문자열로 반환될 경우 UUID 객체로 변환 (PG_UUID 설정 따라 다를 수 있음)
                 try:
                     return uuid.UUID(value)
                 except ValueError:
                      logger.error(f"Invalid UUID format from PostgreSQL result: {value}")
                      return None # 또는 예외 발생
        elif dialect.name == 'sqlite':
            # SQLite stores as string
            if not isinstance(value, uuid.UUID):
                try:
                    return uuid.UUID(value)
                except ValueError:
                     logger.error(f"Invalid UUID format from VARCHAR result: {value}")
                     return None # 또는 예외 발생
            # 이미 UUID 객체인 경우는 그대로 반환
            return value
        else:
            # 다른 DB에서는 hex 문자열을 UUID 객체로 변환
            if not isinstance(value, uuid.UUID):
                try:
                    return uuid.UUID(value) # CHAR(32)에서 읽은 hex 문자열
                except ValueError:
                     logger.error(f"Invalid UUID format from CHAR result: {value}")
                     return None # 또는 예외 발생
            # 이미 UUID 객체인 경우는 그대로 반환
            return value

    # 필요시 추가 메서드 구현 (예: compare_values)
    # def compare_values(self, x, y):
    #     return x == y 

class JSONType(TypeDecorator):
    """
    플랫폼 독립적인 JSON 타입.

    PostgreSQL에서는 네이티브 JSONB 타입을 사용하고,
    다른 데이터베이스(예: SQLite)에서는 TEXT로 저장합니다.
    """
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB())
        else:
            # 다른 DB에서는 TEXT 사용
            return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            # PostgreSQL은 Python dict/list를 직접 처리 가능
            return value
        else:
            # 다른 DB에서는 JSON 문자열로 변환하여 저장
            import json
            return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            # PostgreSQL은 이미 Python dict/list로 반환
            return value
        else:
            # 다른 DB에서는 JSON 문자열을 Python 객체로 변환
            import json
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                 logger.error(f"Failed to decode JSON from database: {value}")
                 return None # 또는 예외 발생 

# Add the new GUID type decorator
class GUID(TypeDecorator):
    """데이터베이스 독립적인 GUID 타입
    
    SQLite에서는 VARCHAR로, 다른 DB에서는 UUID로 처리합니다.
    """
    impl = VARCHAR # Use VARCHAR(32)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        # elif dialect.name == 'sqlite': -> Simplify: Default to VARCHAR for others
        #    return dialect.type_descriptor(VARCHAR(32))
        else:
            # Default to VARCHAR(32) for other potential dialects (like SQLite)
            return dialect.type_descriptor(VARCHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        # elif dialect.name == 'postgresql': -> Simplify
        #    return value if isinstance(value, uuid.UUID) else str(value)
        # elif dialect.name == 'sqlite':
        #    return str(value)
        # else:
        #    return str(value)
        # Always store as string for non-PostgreSQL DBs
        return str(value) if dialect.name != 'postgresql' else value

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        # Regardless of dialect, try converting to UUID object
        # try:
        #    return uuid.UUID(value)
        # except (ValueError, TypeError):
        #    # Handle cases where the value might not be a valid UUID string
        #    # Depending on requirements, might return None or raise error
        #    return value # Or return None / raise
        if not isinstance(value, uuid.UUID):
             try:
                 return uuid.UUID(value)
             except (TypeError, ValueError):
                 # Log error or return original value if conversion fails
                 logger.warning(f"Could not convert value '{value}' to UUID, returning original.")
                 return value # Return original value if conversion fails
        return value # Return UUID object if already is one or converted successfully 

class IPAddress(TypeDecorator):
    """Custom IP Address Type using VARCHAR storage."""
    impl = VARCHAR(45) # Store as string, length covers IPv6
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        # Store the string representation
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        # Convert back to ipaddress object
        try:
            # Use ip_address factory function for flexibility (IPv4/IPv6)
            return ipaddress.ip_address(value)
        except ValueError:
            # Handle invalid IP format stored in DB if necessary
            logger.error(f"Invalid IP address format retrieved from DB: {value}")
            return None # Or raise an error 