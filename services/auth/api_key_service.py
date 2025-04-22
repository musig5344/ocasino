from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from models.domain.api_key import APIKey
from core.security import generate_api_key, hash_api_key
from api.errors.exceptions import PartnerNotFoundError

class APIKeyService:
    def __init__(self, db: Session):
        self.db = db

    async def create_api_key(self, partner_id: str, description: Optional[str] = None) -> APIKey:
        """새로운 API 키 생성"""
        api_key = generate_api_key()
        hashed_key = hash_api_key(api_key)

        db_api_key = APIKey(
            key=api_key,
            hashed_key=hashed_key,
            partner_id=partner_id,
            description=description
        )

        try:
            self.db.add(db_api_key)
            self.db.commit()
            self.db.refresh(db_api_key)
            return db_api_key
        except IntegrityError:
            self.db.rollback()
            raise PartnerNotFoundError(partner_id)

    async def get_by_key(self, api_key: str) -> Optional[APIKey]:
        """API 키로 조회"""
        return self.db.query(APIKey).filter(APIKey.key == api_key).first()

    async def deactivate_api_key(self, api_key_id: str) -> bool:
        """API 키 비활성화"""
        api_key = self.db.query(APIKey).filter(APIKey.id == api_key_id).first()
        if not api_key:
            return False

        api_key.is_active = False
        self.db.commit()
        return True 