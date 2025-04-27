import enum

class PartnerStatus(enum.Enum):
    """Enum for partner status."""
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"

class CommissionModel(enum.Enum):
    """Enum for commission models."""
    REVENUE_SHARE = "revenue_share"
    CPA = "cpa"
    HYBRID = "hybrid"
    # Add other models as needed

class PartnerType(enum.Enum):
    """Enum for partner types."""
    OPERATOR = "operator"
    AGGREGATOR = "aggregator"
    AFFILIATE = "affiliate"
    CASINO_OPERATOR = "casino_operator"
    PAYMENT_PROVIDER = "payment_provider"
    # Add other types as needed

class PartnerTier(enum.Enum):
    """Enum for partner tiers."""
    BASIC = "basic"
    STANDARD = "standard"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"
    # Add other tiers as needed

# Add GameStatus enum here
class GameStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive" # 또는 disabled
    MAINTENANCE = "maintenance"
    DISCONTINUED = "discontinued" # 또는 deprecated 

# Add GameCategory enum here
class GameCategory(str, enum.Enum):
    """게임 카테고리"""
    SLOTS = "slots"              # 슬롯 머신
    TABLE_GAMES = "table_games"  # 테이블 게임
    LIVE_CASINO = "live_casino"  # 라이브 카지노
    POKER = "poker"              # 포커
    BINGO = "bingo"              # 빙고
    LOTTERY = "lottery"          # 로또
    SPORTS = "sports"            # 스포츠 베팅
    ARCADE = "arcade"            # 아케이드 

class SessionStatus(str, enum.Enum):
    """게임 세션 상태"""
    ACTIVE = "active"
    ENDED = "ended"      # 정상적으로 종료된 세션
    EXPIRED = "expired"  # 비활성으로 인해 만료된 세션
    ERROR = "error"      # 오류 상태의 세션

# Add ValueType enum for PartnerSetting
class ValueType(str, enum.Enum):
    """파트너 설정 값의 데이터 타입"""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    JSON = "json"
    # Add other types as needed