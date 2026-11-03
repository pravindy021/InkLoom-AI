from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.brand_guideline import BrandGuideline
from app.models.content_review import ContentReview, ReviewFinding
from app.models.review_comment import ReviewAuditEvent
from app.services.auth_service import require_roles
from app.services.report_exports import analytics_csv, analytics_report_pdf
from app.services.governance_insights import build_governance_insights
from app.services.risk_intelligence import calculate_risk

router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_roles("admin", "reviewer", "contributor"))],
)


def _review_window(query, start_date: Optional[date], end_date: Optional[date]):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be on or before end_date.",
        )
    if start_date:
        query = query.filter(
            ContentReview.created_at
            >= datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        )
    if end_date:
        query = query.filter(
            ContentReview.created_at
            < datetime.combine(
                end_date + timedelta(days=1),
                time.min,
                tzinfo=timezone.utc,
            )
        )
    return query


def _review_ids(db: Session, start_date: Optional[date], end_date: Optional[date]):
    query = _review_window(db.query(ContentReview.id), start_date, end_date)
    return query.subquery()


@router.get("/summary")
def analytics_summary(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
):
    review_query = _review_window(db.query(ContentReview), start_date, end_date)
    review_ids = _review_ids(db, start_date, end_date)
    finding_query = db.query(ReviewFinding).join(
        review_ids, ReviewFinding.review_id == review_ids.c.id
    )

    total_reviews = review_query.count()
    total_issues = finding_query.count()
    severity_counts = {
        severity: count
        for severity, count in (
            db.query(ReviewFinding.severity, func.count(ReviewFinding.id))
            .join(review_ids, ReviewFinding.review_id == review_ids.c.id)
            .group_by(ReviewFinding.severity)
        )
    }
    for severity in ("critical", "high", "medium", "low"):
        severity_counts.setdefault(severity, 0)

    categories = [
        {"category": name, "count": count}
        for name, count in (
            db.query(ReviewFinding.category, func.count(ReviewFinding.id))
            .join(review_ids, ReviewFinding.review_id == review_ids.c.id)
            .group_by(ReviewFinding.category)
            .order_by(
                func.count(ReviewFinding.id).desc(), ReviewFinding.category.asc()
            )
        ).all()
    ]
    statuses = [
        {"status": name, "count": count}
        for name, count in (
            db.query(ContentReview.status, func.count(ContentReview.id))
            .join(review_ids, ContentReview.id == review_ids.c.id)
            .group_by(ContentReview.status)
            .order_by(ContentReview.status.asc())
        ).all()
    ]
    guideline_counts = Counter(
        {
            name: count
            for name, count in (
                db.query(ReviewFinding.source, func.count(ReviewFinding.id))
                .join(review_ids, ReviewFinding.review_id == review_ids.c.id)
                .filter(ReviewFinding.guideline_id.is_not(None))
                .group_by(ReviewFinding.source)
            ).all()
            if name
        }
    )
    frequent_guidelines = [
        {"name": name, "count": count}
        for name, count in guideline_counts.most_common(10)
    ]
    pending_approvals = (
        db.query(func.count(ContentReview.id))
        .join(review_ids, ContentReview.id == review_ids.c.id)
        .filter(ContentReview.status.in_(("pending", "in_review")))
        .scalar()
        or 0
    )

    review_rows = review_query.with_entities(
        ContentReview.id, ContentReview.created_at
    ).all()
    created_by_id = {review_id: created_at for review_id, created_at in review_rows}
    risk_findings_by_review = {}
    for finding in finding_query.all():
        risk_findings_by_review.setdefault(finding.review_id, []).append(
            {
                "category": finding.category,
                "severity": finding.severity,
                "review_status": finding.review_status,
                "confidence": finding.confidence,
                "guideline_id": finding.guideline_id,
                "visual_data": (finding.metadata_json or {}).get("visual_data"),
                "evidence_status": (finding.metadata_json or {}).get("evidence_status"),
                "verification_status": (finding.metadata_json or {}).get(
                    "verification_status"
                ),
            }
        )
    risk_distribution = Counter(
        calculate_risk(
            risk_findings_by_review.get(review_id, [])
        )["level"].lower()
        for review_id, _ in review_rows
    )
    for level in ("low", "medium", "high", "critical"):
        risk_distribution.setdefault(level, 0)
    decision_rows = (
        db.query(
            ReviewAuditEvent.review_id,
            ReviewAuditEvent.reviewer,
            ReviewAuditEvent.new_status,
            ReviewAuditEvent.changed_at,
        )
        .join(review_ids, ReviewAuditEvent.review_id == review_ids.c.id)
        .filter(ReviewAuditEvent.new_status.in_(("approved", "changes_requested")))
        .order_by(ReviewAuditEvent.id.asc())
        .all()
    )
    first_decisions = {}
    reviewer_counts = Counter()
    for review_id, reviewer, new_status, changed_at in decision_rows:
        reviewer_name = reviewer or "Unknown reviewer"
        reviewer_counts[reviewer_name] += 1
        first_decisions.setdefault(
            review_id, (reviewer_name, new_status, changed_at)
        )

    review_durations = []
    for review_id, (reviewer_name, decision, changed_at) in first_decisions.items():
        created_at = created_by_id.get(review_id)
        if created_at and changed_at:
            elapsed = (changed_at - created_at).total_seconds()
            if elapsed >= 0:
                review_durations.append(elapsed)
    average_review_time_hours = (
        round(sum(review_durations) / len(review_durations) / 3600, 2)
        if review_durations
        else None
    )
    reviewer_activity = [
        {"reviewer": name, "decisions": count}
        for name, count in reviewer_counts.most_common(10)
    ]

    verification_counts = Counter()
    for (metadata,) in finding_query.with_entities(ReviewFinding.metadata_json).all():
        verification_status = (metadata or {}).get("verification_status")
        if verification_status:
            verification_counts[verification_status] += 1

    return {
        "total_reviews": total_reviews,
        "total_issues": total_issues,
        "pending_approvals": pending_approvals,
        "issues_by_severity": severity_counts,
        "issues_by_category": categories,
        "status_distribution": statuses,
        "frequent_guidelines": frequent_guidelines,
        "average_review_time_hours": average_review_time_hours,
        "completed_reviews_with_duration": len(review_durations),
        "reviewer_activity": reviewer_activity,
        "claim_verification_statuses": dict(verification_counts),
        "risk_distribution": dict(risk_distribution),
        "date_range": {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        },
    }


@router.get("/export.csv")
def export_analytics_csv(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
):
    summary = analytics_summary(start_date, end_date, db)
    blind_spots = guideline_blind_spots(start_date, end_date, db)
    response = Response(
        content=analytics_csv(summary, blind_spots),
        media_type="text/csv; charset=utf-8",
    )
    response.headers["Content-Disposition"] = 'attachment; filename="inkloom-analytics.csv"'
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/report.pdf")
def export_analytics_pdf(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
):
    summary = analytics_summary(start_date, end_date, db)
    blind_spots = guideline_blind_spots(start_date, end_date, db)
    response = Response(
        content=analytics_report_pdf(summary, blind_spots),
        media_type="application/pdf",
    )
    response.headers["Content-Disposition"] = 'attachment; filename="inkloom-analytics.pdf"'
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/guideline-blind-spots")
def guideline_blind_spots(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
):
    review_ids = _review_ids(db, start_date, end_date)
    counts = (
        db.query(
            ReviewFinding.guideline_id,
            func.count(ReviewFinding.id),
            func.count(func.distinct(ReviewFinding.review_id)),
        )
        .join(review_ids, ReviewFinding.review_id == review_ids.c.id)
        .filter(ReviewFinding.guideline_id.is_not(None))
        .group_by(ReviewFinding.guideline_id)
        .having(func.count(func.distinct(ReviewFinding.review_id)) >= 2)
        .order_by(func.count(func.distinct(ReviewFinding.review_id)).desc())
        .all()
    )
    if not counts:
        return []
    max_count = max(review_count for _, _count, review_count in counts)
    guidelines = {
        item.id: item
        for item in db.query(BrandGuideline)
        .filter(
            BrandGuideline.id.in_(
                [guideline_id for guideline_id, _count, _reviews in counts]
            )
        )
        .all()
    }
    results = []
    for guideline_id, count, review_count in counts:
        item = guidelines.get(guideline_id)
        if item is None:
            continue
        results.append(
            {
                "guideline_id": item.id,
                "guideline": item.name,
                "mentions": count,
                "count": count,
                "review_count": review_count,
                "ambiguity_score": round(review_count / max_count, 2),
                "heuristic": (
                    "Findings across multiple distinct reviews may warrant human "
                    "review; this relative recurrence indicator does not prove "
                    "guideline ambiguity."
                ),
            }
        )
    return results


@router.get("/governance-insights")
def governance_insights(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db),
):
    review_ids = _review_ids(db, start_date, end_date)
    finding_rows = (
        db.query(
            ReviewFinding.id,
            ReviewFinding.review_id,
            ReviewFinding.guideline_id,
            ReviewFinding.category,
            ReviewFinding.severity,
            ReviewFinding.title,
            ReviewFinding.review_status,
            ReviewFinding.matched_text,
            ContentReview.created_at,
        )
        .join(review_ids, ReviewFinding.review_id == review_ids.c.id)
        .join(ContentReview, ContentReview.id == ReviewFinding.review_id)
        .order_by(ReviewFinding.id.asc())
        .all()
    )
    guideline_ids = {
        row.guideline_id
        for row in finding_rows
        if row.guideline_id is not None
    }
    guideline_names = {
        guideline.id: guideline.name
        for guideline in (
            db.query(BrandGuideline)
            .filter(BrandGuideline.id.in_(guideline_ids))
            .all()
            if guideline_ids
            else []
        )
    }
    review_rows = (
        _review_window(
            db.query(ContentReview.id, ContentReview.created_at),
            start_date,
            end_date,
        )
        .order_by(ContentReview.created_at.asc(), ContentReview.id.asc())
        .all()
    )
    review_decisions = (
        db.query(ReviewAuditEvent.new_status, ReviewAuditEvent.changed_at)
        .join(review_ids, ReviewAuditEvent.review_id == review_ids.c.id)
        .filter(
            ReviewAuditEvent.new_status.in_(("approved", "changes_requested"))
        )
        .order_by(ReviewAuditEvent.id.asc())
        .all()
    )
    return {
        **build_governance_insights(
            [
                (
                    row.id,
                    row.review_id,
                    row.guideline_id,
                    row.category,
                    row.severity,
                    row.title,
                    row.review_status,
                    row.matched_text,
                    row.created_at,
                )
                for row in finding_rows
            ],
            guideline_names,
            review_decisions,
            review_rows,
        ),
        "date_range": {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        },
    }
