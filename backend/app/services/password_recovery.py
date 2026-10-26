import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import (
    PASSWORD_RESET_BASE_URL,
)
from app.models.user import PasswordResetToken, RecoveryAttempt
from app.services.email_delivery import EmailDeliveryError, send_email

RESET_TOKEN_BYTES = 32
RESET_TOKEN_LIFETIME = timedelta(minutes=20)
RECOVERY_RATE_WINDOW = timedelta(hours=1)
RECOVERY_EMAIL_LIMIT = 3
RECOVERY_IP_LIMIT = 10
class RecoveryEmailError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fingerprint(kind: str, value: str) -> str:
    return hashlib.sha256(
        "inkloom-recovery-{}:{}".format(kind, value).encode("utf-8")
    ).hexdigest()


def consume_recovery_attempt(
    db: Session, email: str, ip_address: str, now: Optional[datetime] = None
) -> int:
    now = now or utc_now()
    cutoff = now - RECOVERY_RATE_WINDOW
    db.query(RecoveryAttempt).filter(
        RecoveryAttempt.attempted_at < cutoff
    ).delete(synchronize_session=False)
    email_fingerprint = _fingerprint("email", email.strip().lower())
    ip_fingerprint = _fingerprint("ip", ip_address.strip() or "unknown")
    attempts = (
        db.query(RecoveryAttempt)
        .filter(
            RecoveryAttempt.attempted_at >= cutoff,
            or_(
                RecoveryAttempt.email_fingerprint == email_fingerprint,
                RecoveryAttempt.ip_fingerprint == ip_fingerprint,
            ),
        )
        .order_by(RecoveryAttempt.attempted_at.asc())
        .all()
    )
    email_attempts = [
        attempt
        for attempt in attempts
        if attempt.email_fingerprint == email_fingerprint
    ]
    ip_attempts = [
        attempt for attempt in attempts if attempt.ip_fingerprint == ip_fingerprint
    ]
    retry_after = 0
    for matching, limit in (
        (email_attempts, RECOVERY_EMAIL_LIMIT),
        (ip_attempts, RECOVERY_IP_LIMIT),
    ):
        if len(matching) >= limit:
            release = matching[len(matching) - limit].attempted_at
            if release.tzinfo is None:
                release = release.replace(tzinfo=timezone.utc)
            retry_after = max(
                retry_after,
                int(max(1, (release + RECOVERY_RATE_WINDOW - now).total_seconds())),
            )
    if retry_after:
        db.rollback()
        return retry_after

    db.add(
        RecoveryAttempt(
            email_fingerprint=email_fingerprint,
            ip_fingerprint=ip_fingerprint,
            attempted_at=now,
        )
    )
    db.commit()
    return 0


def create_reset_token(
    db: Session, user_id: int, now: Optional[datetime] = None
) -> tuple[str, PasswordResetToken]:
    now = now or utc_now()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user_id,
        PasswordResetToken.used_at.is_(None),
    ).delete(synchronize_session=False)
    raw_token = secrets.token_urlsafe(RESET_TOKEN_BYTES)
    record = PasswordResetToken(
        user_id=user_id,
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=now + RESET_TOKEN_LIFETIME,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return raw_token, record


def reset_url(raw_token: str) -> str:
    return "{}/reset-password#token={}".format(
        PASSWORD_RESET_BASE_URL, raw_token
    )


def send_recovery_email(email: str, url: Optional[str]) -> None:
    body = (
        "A request was made to recover access to an InkLoom workspace account.\n\n"
        + (
            "If this address belongs to an active account, use this single-use link "
            "within 20 minutes:\n{}\n\n".format(url)
            if url
            else "If this address belongs to an active account, request a new "
            "recovery message. If you did not request this, you can ignore this email.\n\n"
        )
        + "If you did not request account recovery, you can ignore this message."
    )
    try:
        send_email(email, "InkLoom workspace password recovery", body)
    except EmailDeliveryError as exc:
        raise RecoveryEmailError("Recovery email delivery failed.") from exc
