import hashlib
import re
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import (
    AUTH_COOKIE_NAME,
    AUTH_COOKIE_SECURE,
    AUTH_SESSION_HOURS,
    SMTP_ENABLED,
)
from app.database import get_db
from app.models.user import AuthSession, PasswordResetToken, User
from app.models.user import AccountAuditEvent, UserInvitation
from app.services.auth_service import (
    authenticate_token,
    clear_login_failures,
    create_session,
    current_user,
    hash_password,
    login_retry_after,
    record_login_failure,
    require_roles,
    serialize_user,
    verify_password,
)
from app.services.collaboration import collaboration_hub
from app.services.email_delivery import EmailDeliveryError
from app.services.invitations import (
    create_invitation,
    invitation_link,
    send_invitation_email,
    utc_now as invitation_utc_now,
)
from app.services.password_recovery import (
    RecoveryEmailError,
    consume_recovery_attempt,
    create_reset_token,
    reset_url,
    send_recovery_email,
    utc_now,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class PasswordRecoveryRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("Enter a valid email address.")
        return email


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=30, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)


class InvitationAcceptance(BaseModel):
    token: str = Field(min_length=30, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["admin", "reviewer", "contributor"] = "contributor"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("Enter a valid email address.")
        return email

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Display name cannot be blank.")
        return value


class UserUpdate(BaseModel):
    role: Literal["admin", "reviewer", "contributor"]
    is_active: bool


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=AUTH_SESSION_HOURS * 60 * 60,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="strict",
        path="/",
    )


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    retry_after = login_retry_after(db, payload.email, client_ip)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    user = (
        db.query(User)
        .filter(User.email == payload.email.strip().lower())
        .first()
    )
    if user is None or not user.is_active or not verify_password(
        payload.password, user.password_hash
    ):
        record_login_failure(db, payload.email, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    clear_login_failures(db, user.email)
    token, _session = create_session(db, user)
    _set_session_cookie(response, token)
    return {"user": serialize_user(user)}


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
def request_password_recovery(
    payload: PasswordRecoveryRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    if not SMTP_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password recovery is not configured. Contact your workspace administrator.",
        )
    client_ip = request.client.host if request.client else "unknown"
    retry_after = consume_recovery_attempt(db, payload.email, client_ip)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many recovery requests. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    user = (
        db.query(User)
        .filter(User.email == payload.email, User.is_active.is_(True))
        .first()
    )
    raw_token = None
    reset_record = None
    if user is not None:
        raw_token, reset_record = create_reset_token(db, user.id)
    try:
        send_recovery_email(
            payload.email,
            reset_url(raw_token) if raw_token else None,
        )
    except RecoveryEmailError as exc:
        if reset_record is not None:
            db.query(PasswordResetToken).filter(
                PasswordResetToken.id == reset_record.id
            ).delete(synchronize_session=False)
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recovery email could not be sent. Contact your workspace administrator.",
        ) from exc
    return {
        "message": "If an active account matches that address, recovery instructions will be sent."
    }


@router.post("/password/reset")
async def reset_password(
    payload: PasswordResetRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    digest = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    now = utc_now()
    record = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == digest,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .first()
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This recovery link is invalid or expired. Request a new one.",
        )
    consumed = db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.id == record.id,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This recovery link is invalid or expired. Request a new one.",
        )
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This recovery link is invalid or expired. Request a new one.",
        )
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete(
        synchronize_session=False
    )
    db.commit()
    await collaboration_hub.disconnect_user(user.id)
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="strict",
    )
    return {"message": "Password reset. Sign in using your new password."}


@router.post("/invitations/accept")
def accept_invitation(
    payload: InvitationAcceptance,
    db: Session = Depends(get_db),
):
    now = invitation_utc_now()
    digest = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    invitation = (
        db.query(UserInvitation)
        .filter(
            UserInvitation.token_hash == digest,
            UserInvitation.used_at.is_(None),
            UserInvitation.revoked_at.is_(None),
            UserInvitation.expires_at > now,
        )
        .first()
    )
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation is invalid or expired. Ask an administrator to resend it.",
        )
    consumed = db.execute(
        update(UserInvitation)
        .where(
            UserInvitation.id == invitation.id,
            UserInvitation.used_at.is_(None),
            UserInvitation.revoked_at.is_(None),
            UserInvitation.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation is invalid or expired. Ask an administrator to resend it.",
        )
    user = db.get(User, invitation.user_id)
    if user is None or user.is_active or not user.must_change_password:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation is invalid or expired. Ask an administrator to resend it.",
        )
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.is_active = True
    db.add(
        AccountAuditEvent(
            actor_user_id=None,
            target_user_id=user.id,
            target_email=user.email,
            action="invitation.accepted",
            details={"role": user.role},
        )
    )
    db.commit()
    return {"message": "Invitation accepted. Sign in with your new password."}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    token = request.cookies.get(AUTH_COOKIE_NAME)
    user = authenticate_token(db, token)
    if user and token:
        from hashlib import sha256

        digest = sha256(token.encode("utf-8")).hexdigest()
        db.query(AuthSession).filter(AuthSession.token_hash == digest).delete()
        db.commit()
        await collaboration_hub.disconnect_user(user.id)
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me")
def me(user: User = Depends(current_user)):
    return serialize_user(user)


@router.post("/password")
async def change_password(
    payload: PasswordChange,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=422,
            detail="Choose a new password different from your current password.",
        )
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
    db.flush()
    token, _session = create_session(db, user)
    await collaboration_hub.disconnect_user(user.id)
    _set_session_cookie(response, token)
    return {"user": serialize_user(user)}


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    users = db.query(User).order_by(User.created_at.asc(), User.id.asc()).all()
    now = invitation_utc_now()
    pending_invitations = {
        invitation.user_id: invitation
        for invitation in db.query(UserInvitation)
        .filter(
            UserInvitation.used_at.is_(None),
            UserInvitation.revoked_at.is_(None),
        )
        .all()
    }
    expired_invitation_ids = {
        user_id
        for (user_id,) in db.query(UserInvitation.user_id)
        .filter(
            UserInvitation.used_at.is_(None),
            UserInvitation.revoked_at.is_(None),
            UserInvitation.expires_at <= now,
        )
        .all()
    }
    return [
        {
            **serialize_user(user),
            "invitation_pending": user.id in pending_invitations,
            "invitation_expired": user.id in expired_invitation_ids,
        }
        for user in users
    ]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    if not SMTP_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email invitations are not configured. Contact your workspace administrator.",
        )
    if db.query(User.id).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="An account already uses that email.")
    user = User(
        email=payload.email,
        display_name=payload.display_name,
        password_hash=hash_password(secrets.token_urlsafe(48)),
        role=payload.role,
        is_active=False,
        must_change_password=True,
    )
    db.add(user)
    db.flush()
    token = create_invitation(db, user)
    db.add(
        AccountAuditEvent(
            actor_user_id=admin.id,
            target_user_id=user.id,
            target_email=user.email,
            action="invitation.created",
            details={"role": user.role},
        )
    )
    db.commit()
    try:
        send_invitation_email(user.email, user.display_name, invitation_link(token))
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The account was created, but the invitation email could not be sent. Retry the invitation from the Admin dashboard.",
        ) from exc
    return {
        "user": {**serialize_user(user), "invitation_pending": True},
        "message": "Invitation email sent.",
    }


@router.post("/users/{user_id}/invitation", status_code=status.HTTP_202_ACCEPTED)
def resend_invitation(
    user_id: int,
    admin: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    if not SMTP_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email invitations are not configured. Contact your workspace administrator.",
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.is_active or not user.must_change_password:
        raise HTTPException(
            status_code=409,
            detail="This account does not have a pending invitation.",
        )
    token = create_invitation(db, user)
    db.add(
        AccountAuditEvent(
            actor_user_id=admin.id,
            target_user_id=user.id,
            target_email=user.email,
            action="invitation.resent",
            details={"role": user.role},
        )
    )
    db.commit()
    try:
        send_invitation_email(user.email, user.display_name, invitation_link(token))
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The invitation email could not be sent. Retry from the Admin dashboard.",
        ) from exc
    return {"message": "Invitation email sent."}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("admin")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.must_change_password and not payload.is_active:
        raise HTTPException(
            status_code=422,
            detail="A pending invitation cannot be deactivated before acceptance.",
        )
    if user.must_change_password and payload.is_active:
        raise HTTPException(
            status_code=422,
            detail="An invited account can only be activated by accepting its invitation.",
        )
    if user.id == admin.id and (payload.role != "admin" or not payload.is_active):
        raise HTTPException(
            status_code=422,
            detail="You cannot deactivate or demote your own active admin account.",
        )
    if user.role == "admin" and (payload.role != "admin" or not payload.is_active):
        other_admin = (
            db.query(User.id)
            .filter(
                User.role == "admin",
                User.is_active.is_(True),
                User.id != user.id,
            )
            .first()
        )
        if not other_admin:
            raise HTTPException(
                status_code=422,
                detail="The workspace must retain at least one active administrator.",
            )
    user.role = payload.role
    user.is_active = payload.is_active
    db.add(
        AccountAuditEvent(
            actor_user_id=admin.id,
            target_user_id=user.id,
            target_email=user.email,
            action="account.updated",
            details={
                "role": user.role,
                "is_active": user.is_active,
            },
        )
    )
    if not user.is_active:
        db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
    db.commit()
    db.refresh(user)
    await collaboration_hub.disconnect_user(user.id)
    return serialize_user(user)
