from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.brand_guideline import BrandGuideline
from app.models.content_review import ContentReview, ReviewFinding
from app.services.auth_service import require_roles

router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_roles("admin", "reviewer", "contributor"))],
)


@router.get("/summary")
def analytics_summary(db: Session = Depends(get_db)):
    total_reviews = db.query(func.count(ContentReview.id)).scalar() or 0
    total_issues = db.query(func.count(ReviewFinding.id)).scalar() or 0
    severity_counts = {
        severity: count
        for severity, count in db.query(
            ReviewFinding.severity, func.count(ReviewFinding.id)
        ).group_by(ReviewFinding.severity)
    }
    for severity in ("critical", "high", "medium", "low"):
        severity_counts.setdefault(severity, 0)

    categories = [
        {"category": name, "count": count}
        for name, count in db.query(
            ReviewFinding.category, func.count(ReviewFinding.id)
        )
        .group_by(ReviewFinding.category)
        .order_by(func.count(ReviewFinding.id).desc(), ReviewFinding.category.asc())
        .all()
    ]
    statuses = [
        {"status": name, "count": count}
        for name, count in db.query(
            ContentReview.status, func.count(ContentReview.id)
        )
        .group_by(ContentReview.status)
        .order_by(ContentReview.status.asc())
        .all()
    ]
    guideline_counts = Counter(
        {
            name: count
            for name, count in db.query(
                ReviewFinding.source, func.count(ReviewFinding.id)
            )
            .filter(ReviewFinding.guideline_id.is_not(None))
            .group_by(ReviewFinding.source)
            .all()
            if name
        }
    )
    frequent_guidelines = [
        {"name": name, "count": count}
        for name, count in guideline_counts.most_common(10)
    ]
    pending_approvals = (
        db.query(func.count(ContentReview.id))
        .filter(ContentReview.status.in_(("pending", "in_review")))
        .scalar()
        or 0
    )
    return {
        "total_reviews": total_reviews,
        "total_issues": total_issues,
        "pending_approvals": pending_approvals,
        "issues_by_severity": severity_counts,
        "issues_by_category": categories,
        "status_distribution": statuses,
        "frequent_guidelines": frequent_guidelines,
    }


@router.get("/guideline-blind-spots")
def guideline_blind_spots(db: Session = Depends(get_db)):
    counts = (
        db.query(ReviewFinding.guideline_id, func.count(ReviewFinding.id))
        .filter(ReviewFinding.guideline_id.is_not(None))
        .group_by(ReviewFinding.guideline_id)
        .order_by(func.count(ReviewFinding.id).desc())
        .all()
    )
    if not counts:
        return []
    max_count = max(count for _, count in counts)
    guidelines = {
        item.id: item
        for item in db.query(BrandGuideline)
        .filter(BrandGuideline.id.in_([guideline_id for guideline_id, _ in counts]))
        .all()
    }
    results = []
    for guideline_id, count in counts:
        item = guidelines.get(guideline_id)
        if item is None:
            continue
        results.append(
            {
                "guideline_id": item.id,
                "guideline": item.name,
                "mentions": count,
                "count": count,
                "ambiguity_score": round(count / max_count, 2),
                "heuristic": (
                    "Relative trigger frequency only. Repeated findings may warrant "
                    "human review; this score does not prove guideline ambiguity."
                ),
            }
        )
    return results
