from typing import Any, Dict

from app.models.content_review import ContentReview


def finding_payload(finding: Any) -> Dict[str, Any]:
    return {
        "id": finding.id,
        "category": finding.category,
        "severity": finding.severity,
        "title": finding.title,
        "explanation": finding.explanation,
        "message": finding.explanation,
        "matched_text": finding.matched_text,
        "suggestion": finding.suggestion,
        "source": finding.source,
        "guideline": finding.source,
        "guideline_id": finding.guideline_id,
        "confidence": finding.confidence,
        "status": finding.review_status,
        "review_status": finding.review_status,
    }


def review_payload(review: ContentReview) -> Dict[str, Any]:
    return {
        "id": review.id,
        "title": review.title,
        "content": review.content,
        "content_type": review.content_type,
        "status": review.status,
        "reviewer": review.reviewer,
        "reviewer_name": review.reviewer,
        "submitted_at": review.created_at,
        "analysis_timestamp": review.analysis_timestamp,
        "issue_count": len(review.findings),
        "findings": [finding_payload(item) for item in review.findings],
        "comments": [
            {
                "id": comment.id,
                "comment": comment.comment,
                "author": comment.author,
                "created_at": comment.created_at,
            }
            for comment in review.comments
        ],
        "revisions": [
            {
                "id": revision.id,
                "content": revision.content,
                "title": revision.title,
                "summary": revision.title or "Revision",
                "created_at": revision.created_at,
            }
            for revision in review.revisions
        ],
    }
