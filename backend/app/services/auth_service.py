import hashlib
import hmac
import math
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import (
    AUTH_SESSION_HOURS,
    BOOTSTRAP_ADMIN_EMAIL,
    BOOTSTRAP_ADMIN_PASSWORD,
)
from app.database import get_db
from app.models.user import AuthSession, LoginAttempt, User

PASSWORD_ITERATIONS = 600_000
SESSION_TOKEN_BYTES = 32
LOGIN_RATE_WINDOW = timedelta(minutes=15)
LOGIN_PAIR_LIMIT = 5
LOGIN_EMAIL_LIMIT = 20
LOGIN_IP_LIMIT = 30


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _login_fingerprint(kind: str, value: str) -> str:
    return hashlib.sha256(
        "inkloom-login-{}:{}".format(kind, value).encode("utf-8")
    ).hexdigest()


def _login_keys(email: str, ip_address: str) -> tuple:
    normalized_email = email.strip().lower()
    normalized_ip = ip_address.strip() or "unknown"
    email_fingerprint = _login_fingerprint("email", normalized_email)
    ip_fingerprint = _login_fingerprint("ip", normalized_ip)
    pair_fingerprint = _login_fingerprint(
        "pair", "{}\0{}".format(normalized_email, normalized_ip)
    )
    return email_fingerprint, ip_fingerprint, pair_fingerprint


def login_retry_after(
    db: Session,
    email: str,
    ip_address: str,
    now: Optional[datetime] = None,
) -> int:
    now = now or _utc_now()
    cutoff = now - LOGIN_RATE_WINDOW
    db.query(LoginAttempt).filter(LoginAttempt.attempted_at < cutoff).delete(
        synchronize_session=False
    )
    email_fingerprint, ip_fingerprint, pair_fingerprint = _login_keys(
        email, ip_address
    )
    attempts = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.attempted_at >= cutoff,
            (
                (LoginAttempt.email_fingerprint == email_fingerprint)
                | (LoginAttempt.ip_fingerprint == ip_fingerprint)
                | (LoginAttempt.pair_fingerprint == pair_fingerprint)
            ),
        )
        .order_by(LoginAttempt.attempted_at.asc())
        .all()
    )
    pair = [
        item for item in attempts if item.pair_fingerprint == pair_fingerprint
    ]
    email_attempts = [
        item for item in attempts if item.email_fingerprint == email_fingerprint
    ]
    ip_attempts = [
        item for item in attempts if item.ip_fingerprint == ip_fingerprint
    ]
    release_times = []
    for matching, limit in (
        (pair, LOGIN_PAIR_LIMIT),
        (email_attempts, LOGIN_EMAIL_LIMIT),
        (ip_attempts, LOGIN_IP_LIMIT),
    ):
        if len(matching) >= limit:
            release_at = _aware(matching[len(matching) - limit].attempted_at)
            release_times.append(release_at + LOGIN_RATE_WINDOW)
    db.flush()
    if not release_times:
        return 0
    return max(1, math.ceil((max(release_times) - now).total_seconds()))


def record_login_failure(
    db: Session, email: str, ip_address: str, now: Optional[datetime] = None
) -> None:
    email_fingerprint, ip_fingerprint, pair_fingerprint = _login_keys(
        email, ip_address
    )
    db.add(
        LoginAttempt(
            email_fingerprint=email_fingerprint,
            ip_fingerprint=ip_fingerprint,
            pair_fingerprint=pair_fingerprint,
            attempted_at=now or _utc_now(),
        )
    )
    db.commit()


def clear_login_failures(db: Session, email: str) -> None:
    email_fingerprint = _login_fingerprint("email", email.strip().lower())
    db.query(LoginAttempt).filter(
        LoginAttempt.email_fingerprint == email_fingerprint
    ).delete(synchronize_session=False)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        salt.hex(),
        derived.hex(),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations_number = int(iterations)
        if not 100_000 <= iterations_number <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            iterations_number,
        )
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def create_session(db: Session, user: User) -> tuple:
    raw_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    db.query(AuthSession).filter(
        AuthSession.expires_at <= _utc_now()
    ).delete(synchronize_session=False)
    session = AuthSession(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=_utc_now() + timedelta(hours=AUTH_SESSION_HOURS),
    )
    db.add(session)
    db.commit()
    return raw_token, session


def authenticate_token(db: Session, raw_token: Optional[str]) -> Optional[User]:
    if not raw_token or len(raw_token) > 256:
        return None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == token_hash)
        .first()
    )
    if session is None:
        return None
    if _aware(session.expires_at) <= _utc_now() or not session.user.is_active:
        db.delete(session)
        db.commit()
        return None
    return session.user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    from app.config import AUTH_COOKIE_NAME

    user = authenticate_token(db, request.cookies.get(AUTH_COOKIE_NAME))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to access this workspace.",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.must_change_password:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Change your temporary password before continuing.",
            )
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your workspace role does not allow this action.",
            )
        return user

    return dependency


def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at,
    }


def bootstrap_admin(db: Session) -> None:
    if not BOOTSTRAP_ADMIN_EMAIL:
        return
    user = db.query(User).filter(User.email == BOOTSTRAP_ADMIN_EMAIL).first()
    if user is not None:
        return
    if db.query(User.id).first() is not None:
        return
    db.add(
        User(
            email=BOOTSTRAP_ADMIN_EMAIL,
            display_name="Workspace Admin",
            password_hash=hash_password(BOOTSTRAP_ADMIN_PASSWORD),
            role="admin",
            is_active=True,
            must_change_password=False,
        )
    )
    db.commit()
