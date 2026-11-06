
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from fastapi.security import HTTPBearer

from app.config import FRONTEND_URL
from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models.invitation import Invitation
from app.models.user import User
from app.schemas.auth import (
    AcceptInviteRequest,
    InviteCreate,
    InviteResponse,
    LoginRequest,
    TokenResponse,
    UserResponse,
)
from app.utils.security import (
    create_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def hash_invitation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_invitation_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return expires_at <= datetime.now(timezone.utc)


@router.post("/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.email == str(data.email).lower())
        .first()
    )

    if (
        not user
        or not user.is_active
        or not verify_password(data.password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    token = create_access_token(
        subject=str(user.id),
        extra_claims={"role": user.role},
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user,
    }


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user),
):
    return current_user


@router.post("/invitations")
def create_invitation(
    data: InviteCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    email = str(data.email).lower()

    existing_user = db.query(User).filter(User.email == email).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    pending_invitations = (
        db.query(Invitation)
        .filter(
            Invitation.email == email,
            Invitation.is_accepted.is_(False),
            Invitation.is_revoked.is_(False),
        )
        .all()
    )

    for old_invitation in pending_invitations:
        if not is_invitation_expired(old_invitation.expires_at):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An active invitation already exists for this email.",
            )

        old_invitation.is_revoked = True

    raw_token = secrets.token_urlsafe(32)

    invitation = Invitation(
        email=email,
        full_name=data.full_name.strip(),
        role=data.role,
        token_hash=hash_invitation_token(raw_token),
        created_by=current_admin.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
    )

    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    return {
        "invitation": InviteResponse.model_validate(invitation),
        "invite_url": f"{FRONTEND_URL}/accept-invite?token={raw_token}",
        "message": "Invitation created. Copy the link and share it securely.",
    }


@router.post("/accept-invite", response_model=TokenResponse)
def accept_invitation(
    data: AcceptInviteRequest,
    db: Session = Depends(get_db),
):
    token_hash = hash_invitation_token(data.token)

    invitation = (
        db.query(Invitation)
        .filter(Invitation.token_hash == token_hash)
        .first()
    )

    if (
        not invitation
        or invitation.is_accepted
        or invitation.is_revoked
        or is_invitation_expired(invitation.expires_at)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation is invalid, expired, or already used.",
        )

    existing_user = (
        db.query(User)
        .filter(User.email == invitation.email)
        .first()
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=invitation.email,
        full_name=invitation.full_name,
        hashed_password=hash_password(data.password),
        role=invitation.role,
        is_active=True,
    )

    invitation.is_accepted = True

    db.add(user)
    db.commit()
    db.refresh(user)

    access_token = create_access_token(
        subject=str(user.id),
        extra_claims={"role": user.role},
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
    }


@router.get("/invitations", response_model=list[InviteResponse])
def list_invitations(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return (
        db.query(Invitation)
        .order_by(Invitation.created_at.desc())
        .all()
    )


@router.delete("/invitations/{invitation_id}")
def revoke_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    invitation = (
        db.query(Invitation)
        .filter(Invitation.id == invitation_id)
        .first()
    )

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found.",
        )

    if invitation.is_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An accepted invitation cannot be revoked.",
        )

    invitation.is_revoked = True
    db.commit()

    return {"message": "Invitation revoked successfully."}


@router.get("/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return (
        db.query(User)
        .order_by(User.created_at.desc())
        .all()
    )
