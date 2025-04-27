"""
Partner Domain Models (SQLAlchemy)
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Set, Dict, Any # Add Dict, Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Enum as EnumType, UniqueConstraint, text, Text # Add Text
from sqlalchemy.orm import relationship, Mapped # Mapped needs to be imported
from sqlalchemy.dialects.postgresql import UUID as PSQL_UUID, CIDR, JSONB

# TODO: Update this import after moving Base and types
from backend.db.database import Base 
from backend.db.types import UUIDType, GUID 

# TODO: Update this import after moving enums
from backend.models.enums import PartnerStatus, CommissionModel, PartnerType, ValueType # Import ValueType

# Keep other model imports inside TYPE_CHECKING for hinting
if TYPE_CHECKING:
    # TODO: Update these imports if models are moved to common/ or other modules
    from backend.models.domain.wallet import Wallet
    from backend.models.domain.audit_log import AuditLog
    # No need to import self-referencing or directly related models like ApiKey here
    # SQLAlchemy handles relationships via strings or direct class references below


class Partner(Base):
    """파트너 모델"""
    __tablename__ = "partners"

    id: Mapped[UUID] = Column(GUID, primary_key=True, default=uuid4)
    code: Mapped[str] = Column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = Column(String(200), index=True, nullable=False)
    partner_type: Mapped[PartnerType] = Column(EnumType(PartnerType), nullable=False)
    status: Mapped[PartnerStatus] = Column(EnumType(PartnerStatus), default=PartnerStatus.PENDING, nullable=False)
    commission_model: Mapped[CommissionModel] = Column(EnumType(CommissionModel), nullable=True)
    commission_rate: Mapped[Optional[float]] = Column(Text, nullable=True) # Store as Text to accommodate descriptions like '10 USD per transaction'

    # Contact / Company Info (Optional)
    contact_name: Mapped[Optional[str]] = Column(String(100))
    contact_email: Mapped[Optional[str]] = Column(String(255), unique=True, index=True) # Email should likely be unique if used for login/contact
    contact_phone: Mapped[Optional[str]] = Column(String(50))
    company_name: Mapped[Optional[str]] = Column(String(200))
    company_address: Mapped[Optional[str]] = Column(Text)
    company_registration_number: Mapped[Optional[str]] = Column(String(100))
    contract_start_date: Mapped[Optional[datetime]] = Column(DateTime(timezone=True))
    contract_end_date: Mapped[Optional[datetime]] = Column(DateTime(timezone=True))
    
    # Meta
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), default=datetime.utcnow, server_default=text("TIMEZONE('utc', now())"))
    updated_at: Mapped[datetime] = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("TIMEZONE('utc', now())"), server_onupdate=text("TIMEZONE('utc', now())"))
    is_active: Mapped[bool] = Column(Boolean, default=True, nullable=False) # Add is_active for soft deletes

    # Relationships
    # Use Mapped annotation and string references for forward refs
    wallets: Mapped[List["Wallet"]] = relationship(back_populates="partner", cascade="all, delete-orphan")
    api_keys: Mapped[List["ApiKey"]] = relationship(back_populates="partner", cascade="all, delete-orphan")
    settings: Mapped[List["PartnerSetting"]] = relationship(back_populates="partner", cascade="all, delete-orphan")
    allowed_ips: Mapped[List["PartnerIP"]] = relationship(back_populates="partner", cascade="all, delete-orphan")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="partner")
    
    __table_args__ = (
        UniqueConstraint('code', name='uq_partner_code'),
        UniqueConstraint('contact_email', name='uq_partner_contact_email'), # If email is unique
    )


class ApiKey(Base):
    """파트너 API 키 모델"""
    __tablename__ = "api_keys"

    id: Mapped[UUID] = Column(GUID, primary_key=True, default=uuid4)
    partner_id: Mapped[UUID] = Column(GUID, ForeignKey("partners.id"), nullable=False, index=True)
    key: Mapped[str] = Column(String(100), unique=True, index=True, nullable=False) # The visible part of the key
    hashed_secret: Mapped[str] = Column(String(255), nullable=False) # Store the hashed secret
    name: Mapped[str] = Column(String(100), nullable=False)
    permissions: Mapped[Optional[List[str]]] = Column(JSONB, nullable=True) # Store permissions as JSON
    is_active: Mapped[bool] = Column(Boolean, default=True, nullable=False)
    expires_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = Column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), default=datetime.utcnow, server_default=text("TIMEZONE('utc', now())"))
    updated_at: Mapped[datetime] = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("TIMEZONE('utc', now())"), server_onupdate=text("TIMEZONE('utc', now())"))

    # Relationship
    partner: Mapped["Partner"] = relationship(back_populates="api_keys")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="api_key")
    
    __table_args__ = (UniqueConstraint('key', name='uq_api_key_key'),)


class PartnerSetting(Base):
    """파트너 설정 모델 (Key-Value)"""
    __tablename__ = "partner_settings"

    id: Mapped[UUID] = Column(GUID, primary_key=True, default=uuid4)
    partner_id: Mapped[UUID] = Column(GUID, ForeignKey("partners.id"), nullable=False, index=True)
    setting_key: Mapped[str] = Column(String(100), nullable=False, index=True)
    setting_value: Mapped[str] = Column(Text, nullable=False)
    value_type: Mapped[ValueType] = Column(EnumType(ValueType), default=ValueType.STRING, nullable=False) # Type info for casting
    description: Mapped[Optional[str]] = Column(Text)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), default=datetime.utcnow, server_default=text("TIMEZONE('utc', now())"))
    updated_at: Mapped[datetime] = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("TIMEZONE('utc', now())"), server_onupdate=text("TIMEZONE('utc', now())"))
    is_encrypted: Mapped[bool] = Column(Boolean, default=False, nullable=False) # Flag for sensitive settings

    # Relationship
    partner: Mapped["Partner"] = relationship(back_populates="settings")
    
    __table_args__ = (UniqueConstraint('partner_id', 'setting_key', name='uq_partner_setting_key'),)


class PartnerIP(Base):
    """파트너 IP 화이트리스트 모델"""
    __tablename__ = "partner_ips"

    id: Mapped[UUID] = Column(GUID, primary_key=True, default=uuid4)
    partner_id: Mapped[UUID] = Column(GUID, ForeignKey("partners.id"), nullable=False, index=True)
    ip_address: Mapped[str] = Column(String(50), nullable=False) # Store as string to handle IPv4/IPv6/CIDR
    description: Mapped[Optional[str]] = Column(String(255))
    is_active: Mapped[bool] = Column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = Column(DateTime(timezone=True), default=datetime.utcnow, server_default=text("TIMEZONE('utc', now())"))
    updated_at: Mapped[datetime] = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("TIMEZONE('utc', now())"), server_onupdate=text("TIMEZONE('utc', now())"))

    # Relationship
    partner: Mapped["Partner"] = relationship(back_populates="allowed_ips")
    
    __table_args__ = (UniqueConstraint('partner_id', 'ip_address', name='uq_partner_ip_address'),) 