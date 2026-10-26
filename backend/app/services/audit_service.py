from typing import Optional

from sqlalchemy.orm import Session

from app.models.content_review import ContentReview
from app.models.review_comment import ReviewAuditEvent


def record_status_change(
    db: Session,
    review: ContentReview,
    new_status: str,
    reviewer: Optional[str],
) -> None:
    previous_status = review.status
    review.status = new_status
    if reviewer is not None:
        review.reviewer = reviewer
    db.add(
        ReviewAuditEvent(
            review_id=review.id,
            previous_status=previous_status,
            new_status=new_status,
            reviewer=reviewer,
        )
    )
