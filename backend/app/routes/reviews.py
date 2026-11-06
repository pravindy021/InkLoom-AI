
import json

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.content_review import ContentReview, ReviewRevision
from app.models.review_comment import ReviewActivity, ReviewComment
from app.models.user import User
from app.schemas.reviews import CommentCreate, RevisionCreate, StatusUpdate
from app.services.audit_service import record_status_change
from app.services.activity_service import record_activity
from app.services.collaboration import collaboration_hub
from app.services.review_service import review_payload
from app.utils.security import decode_access_token

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


def _get_review(db: Session, review_id: int) -> ContentReview:
    review = (
        db.query(ContentReview)
        .options(
            selectinload(ContentReview.findings),
            selectinload(ContentReview.comments),
            selectinload(ContentReview.revisions),
        )
        .filter(ContentReview.id == review_id)
        .first()
    )

    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")

    return review


def _user_identity(user: User) -> str:
    return (user.full_name or user.email).strip()


@router.get("")
def list_reviews(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    review_status: str = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ContentReview)

    if review_status:
        if review_status not in {
            "pending",
            "in_review",
            "approved",
            "changes_requested",
        }:
            raise HTTPException(
                status_code=422,
                detail="Unsupported review status.",
            )

        query = query.filter(ContentReview.status == review_status)

    total = query.count()

    reviews = (
        query.options(selectinload(ContentReview.findings))
        .order_by(ContentReview.created_at.desc(), ContentReview.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = []

    for review in reviews:
        items.append(
            {
                "id": review.id,
                "title": review.title,
                "content_type": review.content_type,
                "status": review.status,
                "reviewer": review.reviewer,
                "reviewer_name": review.reviewer,
                "submitted_at": review.created_at,
                "analysis_timestamp": review.analysis_timestamp,
                "issue_count": len(review.findings),
            }
        )

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{review_id}")
def get_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return review_payload(_get_review(db, review_id))


@router.get("/{review_id}/activity")
def get_review_activity(
    review_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_review(db, review_id)

    entries = (
        db.query(ReviewActivity)
        .filter(ReviewActivity.review_id == review_id)
        .order_by(ReviewActivity.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        {
            "id": entry.id,
            "action": entry.action,
            "actor": entry.actor,
            "details": entry.details,
            "created_at": entry.created_at,
        }
        for entry in entries
    ]


@router.patch("/{review_id}/status")
async def update_status(
    review_id: int,
    payload: StatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    review = _get_review(db, review_id)
    actor = _user_identity(current_user)

    record_status_change(
        db,
        review,
        payload.status,
        actor,
    )

    record_activity(
        db,
        review.id,
        "status_changed",
        actor=actor,
        details={"status": payload.status},
    )

    db.commit()
    db.refresh(review)

    serialized = review_payload(_get_review(db, review_id))

    await collaboration_hub.broadcast(
        review_id,
        {
            "type": "status_changed",
            "payload": {
                "status": payload.status,
                "reviewer": actor,
            },
        },
    )

    return serialized


@router.post("/{review_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    review_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_review(db, review_id)
    actor = _user_identity(current_user)

    comment = ReviewComment(
        review_id=review_id,
        comment=payload.comment,
        author=actor,
    )

    db.add(comment)
    db.flush()

    record_activity(
        db,
        review_id,
        "comment_added",
        actor=actor,
        details={"comment_id": comment.id},
    )

    db.commit()
    db.refresh(comment)

    result = {
        "id": comment.id,
        "comment": comment.comment,
        "author": comment.author,
        "created_at": comment.created_at,
    }

    await collaboration_hub.broadcast(
        review_id,
        {
            "type": "comment_created",
            "payload": result,
        },
    )

    return result


@router.post("/{review_id}/revisions", status_code=status.HTTP_201_CREATED)
async def add_revision(
    review_id: int,
    payload: RevisionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    review = _get_review(db, review_id)
    actor = _user_identity(current_user)

    revision = ReviewRevision(
        review_id=review_id,
        content=payload.content,
        title=payload.title,
    )

    db.add(revision)
    db.flush()

    review.content = payload.content

    record_activity(
        db,
        review_id,
        "revision_added",
        actor=actor,
        details={"title": payload.title},
    )

    db.commit()
    db.refresh(revision)

    result = {
        "id": revision.id,
        "content": revision.content,
        "title": revision.title,
        "summary": revision.title or "Revision",
        "created_at": revision.created_at,
    }

    await collaboration_hub.broadcast(
        review_id,
        {
            "type": "revision_created",
            "payload": result,
        },
    )

    return result


@router.websocket("/{review_id}/collaboration")
async def review_collaboration(
    websocket: WebSocket,
    review_id: int,
    db: Session = Depends(get_db),
):
    # Browser WebSocket connections use the access token in the query string.
    token = websocket.query_params.get("token")

    # Also support Bearer authentication for non-browser WebSocket clients.
    if not token:
        authorization = websocket.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()

    if not token:
        await websocket.close(code=4401, reason="Authentication required.")
        return

    try:
        token_payload = decode_access_token(token)
        subject = token_payload.get("sub")

        if not subject:
            raise ValueError("Token subject missing.")

        user_id = int(subject)

    except (jwt.InvalidTokenError, ValueError, TypeError):
        await websocket.close(code=4401, reason="Invalid or expired token.")
        return

    current_user = db.query(User).filter(User.id == user_id).first()

    if current_user is None or not current_user.is_active:
        await websocket.close(code=4403, reason="User access is disabled.")
        return

    review = db.get(ContentReview, review_id)

    if review is None:
        await websocket.close(code=4404, reason="Review not found.")
        return

    actor = _user_identity(current_user)

    await collaboration_hub.connect(review_id, websocket)

    try:
        await collaboration_hub.broadcast(
            review_id,
            {
                "type": "presence",
                "payload": {
                    "event": "joined",
                    "review_id": review_id,
                    "user": actor,
                },
            },
        )

        while True:
            raw = await websocket.receive_text()

            if len(raw.encode("utf-8")) > 102400:
                await websocket.send_json(
                    {"type": "error", "message": "Message too large."}
                )
                continue

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "message": "Send valid JSON."}
                )
                continue

            if not isinstance(message, dict):
                await websocket.send_json(
                    {"type": "error", "message": "Invalid collaboration event."}
                )
                continue

            event_type = message.get("type")

            if event_type == "draft_changed":
                content = message.get("content")

                if (
                    not isinstance(content, str)
                    or len(content.encode("utf-8")) > 100_000
                ):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "Invalid draft content or draft too large.",
                        }
                    )
                    continue

                await collaboration_hub.broadcast(
                    review_id,
                    {
                        "type": "draft_changed",
                        "payload": {
                            "content": content,
                            "user": actor,
                        },
                    },
                )
                continue

            if event_type not in {"typing", "presence"}:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Unsupported collaboration event.",
                    }
                )
                continue

            await collaboration_hub.broadcast(
                review_id,
                {
                    "type": event_type,
                    "payload": {
                        "user": actor,
                        "active": bool(message.get("active", True)),
                    },
                },
            )

    except WebSocketDisconnect:
        pass

    finally:
        await collaboration_hub.disconnect(review_id, websocket)
