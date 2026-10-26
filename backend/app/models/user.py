from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="contributor")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user: Mapped[User] = relationship(back_populates="sessions")


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_time", "email_fingerprint", "attempted_at"),
        Index("ix_login_attempts_ip_time", "ip_fingerprint", "attempted_at"),
        Index("ix_login_attempts_pair_time", "pair_fingerprint", "attempted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    pair_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RecoveryAttempt(Base):
    __tablename__ = "recovery_attempts"
    __table_args__ = (
        Index("ix_recovery_attempt_email_time", "email_fingerprint", "attempted_at"),
        Index("ix_recovery_attempt_ip_time", "ip_fingerprint", "attempted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class UserInvitation(Base):
    __tablename__ = "user_invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AccountAuditEvent(Base):
    __tablename__ = "account_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    target_user_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    target_email: Mapped[str] = mapped_column(String(254), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
