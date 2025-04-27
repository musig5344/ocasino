"""
국제화(i18n) 지원 모듈
"""

# 임시로 빈 파일. 추후 구현 필요.
class Translator:
    def __call__(self, key: str) -> str:
        return key # 임시로 키 자체를 반환

def get_translator():
    return Translator() # 임시 Translator 인스턴스 반환

pass 