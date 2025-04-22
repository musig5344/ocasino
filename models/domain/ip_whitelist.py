from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from db.database import Base

class IPWhitelist(Base):
    __tablename__ = "ip_whitelist"

    id = Column(String, primary_key=True, index=True)
    ip_address = Column(String, unique=True, index=True)
    partner_id = Column(String, ForeignKey("partners.id"))
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계
    partner = relationship("Partner", back_populates="ip_whitelist") 