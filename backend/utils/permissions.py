# backend/utils/permissions.py
import logging
from typing import Union, List, Dict, Optional, Set
from functools import lru_cache

logger = logging.getLogger(__name__)

def check_permission(
    permissions: Union[List[str], Dict[str, List[str]], None], 
    required_permission: str
) -> bool:
    """주어진 권한 목록/딕셔너리에 특정 권한이 있는지 확인합니다.
    
    권한 형식은 'resource.action' (예: 'partners.update.all')을 사용합니다.
    와일드카드('*')를 지원합니다.
    
    Args:
        permissions: 확인할 권한 데이터 (리스트 또는 딕셔너리 형태)
        required_permission: 필요한 권한 문자열

    Returns:
        bool: 권한 보유 여부
    """
    if permissions is None:
        logger.debug("Permissions object is None, denying access")
        return False
    
    if not required_permission:
        logger.warning("Empty required_permission provided, denying access")
        return False

    try:
        # 우선 캐시에서 결과 확인
        # 수정: _check_permission_internal 호출 전에 해시 가능한 형태로 변환
        hashable_permissions = prepare_permissions_for_cache(permissions)
        return _check_permission_internal(hashable_permissions, required_permission)
    except Exception as e:
        logger.error(f"Error checking permission '{required_permission}': {e}")
        return False


@lru_cache(maxsize=256)
def _check_permission_internal(
    permissions_hashable: Union[tuple, frozenset, str], 
    required_permission: str
) -> bool:
    """권한 확인 내부 로직 (캐싱 지원)"""
    # 해시 가능한 타입에서 원래 권한 데이터로 변환
    if isinstance(permissions_hashable, tuple):
        permissions = list(permissions_hashable)
    elif isinstance(permissions_hashable, frozenset):
        permissions = {k: list(v) for k, v in permissions_hashable}
    else:
        permissions = permissions_hashable
    
    if not permissions:
        return False
        
    try:
        parts = required_permission.split('.')
        if len(parts) < 2:
            logger.warning(f"Invalid required_permission format: {required_permission}. Expected 'resource.action'.")
            return False
            
        resource, action = parts[0], '.'.join(parts[1:])  # resource.action 또는 resource.action.scope 형식 지원
    except ValueError:
        logger.warning(f"Invalid required_permission format: {required_permission}. Expected 'resource.action'.")
        return False

    if isinstance(permissions, list):
        # 리스트 형태 권한: ["partners.read", "partners.*", "*.manage", "*"]
        if required_permission in permissions:
            return True
        if "*" in permissions:
            return True
        if f"{resource}.*" in permissions:
            return True
        if f"*.{action}" in permissions:
            return True
            
    elif isinstance(permissions, dict):
        # 딕셔너리 형태 권한: {"partners": ["read", "*"], "*": ["manage"]}
        if resource in permissions:
            if action in permissions[resource]:
                return True
            if "*" in permissions[resource]:
                return True
                
        if "*" in permissions:
            if action in permissions["*"]:
                return True
            if "*" in permissions["*"]:
                return True
    else:
        logger.warning(f"Unknown permission format type: {type(permissions)}")
        
    return False


def prepare_permissions_for_cache(permissions: Union[List[str], Dict[str, List[str]]]) -> Union[tuple, frozenset]:
    """권한 데이터를 캐시 키로 사용하기 위해 해시 가능한 형태로 변환합니다."""
    if isinstance(permissions, list):
        return tuple(sorted(permissions))
    elif isinstance(permissions, dict):
        return frozenset((k, tuple(sorted(v))) for k, v in sorted(permissions.items()))
    return permissions


def has_any_permission(
    permissions: Union[List[str], Dict[str, List[str]], None],
    required_permissions: List[str]
) -> bool:
    """여러 권한 중 하나라도 보유하고 있는지 확인합니다."""
    if not permissions or not required_permissions:
        return False
        
    return any(check_permission(permissions, perm) for perm in required_permissions)


def has_all_permissions(
    permissions: Union[List[str], Dict[str, List[str]], None],
    required_permissions: List[str]
) -> bool:
    """모든 필요 권한을 보유하고 있는지 확인합니다."""
    if not permissions or not required_permissions:
        return False
        
    return all(check_permission(permissions, perm) for perm in required_permissions)


def get_resource_actions(
    permissions: Union[List[str], Dict[str, List[str]], None],
    resource: str
) -> Set[str]:
    """특정 리소스에 대한 모든, 허용된 액션을 반환합니다."""
    if permissions is None:
        return set()
    
    actions = set()
    
    if isinstance(permissions, list):
        # 리스트 형태 권한에서 리소스 관련 액션 추출
        for perm in permissions:
            if perm == "*":  # 모든 것에 대한 와일드카드
                return {"*"}
                
            parts = perm.split(".")
            if len(parts) >= 2:
                perm_resource = parts[0]
                perm_action = ".".join(parts[1:])
                
                if perm_resource == resource:
                    actions.add(perm_action)
                elif perm_resource == "*":
                    actions.add(perm_action)
    
    elif isinstance(permissions, dict):
        # 딕셔너리 형태 권한에서 리소스 관련 액션 추출
        if "*" in permissions:
            actions.update(permissions["*"])
            if "*" in permissions["*"]:
                return {"*"}
                
        if resource in permissions:
            actions.update(permissions[resource])
            if "*" in permissions[resource]:
                return {"*"}
    
    return actions


def normalize_permissions(permissions: Union[List[str], Dict[str, List[str]], None]) -> Dict[str, List[str]]:
    """권한 데이터를 표준화된 딕셔너리 형태로 변환합니다."""
    if permissions is None:
        return {}
        
    result = {}
    
    if isinstance(permissions, list):
        # 리스트를 딕셔너리로 변환
        for perm in permissions:
            if perm == "*":
                result["*"] = ["*"]
                continue
                
            parts = perm.split(".")
            if len(parts) >= 2:
                resource = parts[0]
                action = ".".join(parts[1:])
                
                if resource not in result:
                    result[resource] = []
                result[resource].append(action)
    
    elif isinstance(permissions, dict):
        # 이미 딕셔너리면 복사만 수행
        for resource, actions in permissions.items():
            result[resource] = list(actions)
    
    return result