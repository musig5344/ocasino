from fastapi import Request, Depends, Header
from typing import Optional, Dict, Any, Callable
import json
import logging
import os
from functools import lru_cache

from backend.core.config import settings
from backend.utils.request_context import get_request_attribute, set_request_attribute

logger = logging.getLogger(__name__)

# 언어 리소스 경로
LOCALE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "locales")

class Translator:
    """
    번역 서비스 클래스
    
    다국어 지원을 위한 번역 기능을 제공합니다.
    """
    
    def __init__(self, locale: str = "en"):
        """
        번역기 초기화
        
        Args:
            locale: 언어 코드 (기본: 영어)
        """
        self.locale = locale
        self.translations = self._load_translations(locale)
    
    def _load_translations(self, locale: str) -> Dict[str, str]:
        """
        언어 파일 로드
        
        Args:
            locale: 언어 코드
            
        Returns:
            Dict[str, str]: 번역 사전
        """
        # 기본 영어 번역 로드
        translations = {}
        
        # 영어가 아닌 경우에만 추가 번역 로드
        if locale != "en":
            try:
                locale_file = os.path.join(LOCALE_DIR, f"{locale}.json")
                if os.path.exists(locale_file):
                    with open(locale_file, "r", encoding="utf-8") as f:
                        translations = json.load(f)
                else:
                    logger.warning(f"Translation file for locale '{locale}' not found")
            except Exception as e:
                logger.error(f"Error loading translations for locale '{locale}': {e}")
        
        return translations
    
    def translate(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """
        텍스트 번역
        
        Args:
            key: 번역 키
            default: 기본 텍스트 (번역이 없는 경우)
            kwargs: 포맷 변수
            
        Returns:
            str: 번역된 텍스트
        """
        # 번역 키 확인
        text = self.translations.get(key)
        
        # 번역이 없으면 기본값 사용
        if text is None:
            if default:
                text = default
            else:
                return key
        
        # 포맷 변수 적용
        if kwargs:
            try:
                text = text.format(**kwargs)
            except KeyError as e:
                logger.warning(f"Missing format key in translation: {e}")
                # 포맷 실패 시 원본 반환
                return text
        
        return text
    
    def __call__(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """
        번역기 호출 (translate의 단축 형태)
        
        Args:
            key: 번역 키
            default: 기본 텍스트 (번역이 없는 경우)
            kwargs: 포맷 변수
            
        Returns:
            str: 번역된 텍스트
        """
        return self.translate(key, default, **kwargs)

@lru_cache(maxsize=10)
def get_translator_instance(locale: str) -> Translator:
    """
    번역기 인스턴스 가져오기 (캐싱)
    
    Args:
        locale: 언어 코드
        
    Returns:
        Translator: 번역기 인스턴스
    """
    return Translator(locale)

def get_locale(
    accept_language: Optional[str] = Header(None, alias="Accept-Language")
) -> str:
    """
    요청에서 언어 코드 추출
    
    Args:
        accept_language: Accept-Language 헤더
        
    Returns:
        str: 언어 코드
    """
    # 컨텍스트에서 이미 설정된 로케일 확인
    locale = get_request_attribute("locale")
    if locale:
        return locale
    
    # 지원하는 언어 목록
    supported_locales = settings.SUPPORTED_LOCALES
    default_locale = settings.DEFAULT_LOCALE
    
    if not accept_language:
        return default_locale
    
    # 우선순위에 따른 언어 코드 파싱
    for part in accept_language.split(","):
        locale_parts = part.strip().split(";")
        locale = locale_parts[0].lower().replace("-", "_")
        
        # 정확히 일치하는 언어
        if locale in supported_locales:
            set_request_attribute("locale", locale)
            return locale
        
        # 주요 언어 코드만 확인 (예: 'en_US' -> 'en')
        main_locale = locale.split("_")[0]
        if main_locale in supported_locales:
            set_request_attribute("locale", main_locale)
            return main_locale
    
    # 기본 언어 반환
    set_request_attribute("locale", default_locale)
    return default_locale

async def get_translator(
    locale: str = Depends(get_locale)
) -> Translator:
    """
    번역기 가져오기
    
    Args:
        locale: 언어 코드
        
    Returns:
        Translator: 번역기 인스턴스
    """
    return get_translator_instance(locale)