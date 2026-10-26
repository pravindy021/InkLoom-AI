from typing import Optional

from sqlalchemy.orm import Session

from app.models.review_comment import ReviewActivity


def record_activity(
    db: Session,
    review_id: int,
    action: str,
    actor: Optional[str] = None,
    details: Optional[dict] = None,
) -> ReviewActivity:
    entry = ReviewActivity(
        review_id=review_id,
        action=action,
        actor=actor,
        details=details or {},
    )
    db.add(entry)
    return entry
