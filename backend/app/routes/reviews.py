import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.brand_guideline import BrandGuideline
from app.models.content_review import (
    ContentReview,
    ReviewAnalysisRun,
    ReviewFinding,
    ReviewRevision,
)
from app.models.review_comment import ReviewActivity, ReviewComment
from app.models.source_document import SourceDocument
from app.schemas.reviews import CommentCreate, RevisionCreate, StatusUpdate
from app.services.audit_service import record_status_change
from app.services.activity_service import record_activity
from app.services.collaboration import collaboration_hub
from app.services.review_service import review_payload
from app.services.claim_checker import check_promotional_claims, factual_claim_excerpts
from app.services.factual_verifier import verification_fields
from app.services.source_retrieval import (
    EmbeddingProviderError,
    retrieve_evidence,
    retrieve_lexical_evidence,
    retrieval_method,
)
from app.services.text_analyzer import analyze_text
from app.config import MAX_CONTENT_LENGTH
from datetime import datetime, timezone
from app.models.user import User
from app.services.auth_service import authenticate_token, require_roles
from app.config import CORS_ORIGINS

router = APIRouter(
    prefix="/api/reviews",
    tags=["reviews"],
)


def _get_review(db: Session, review_id: int) -> ContentReview:
    review = (
        db.query(ContentReview)
        .options(
            selectinload(ContentReview.findings),
            selectinload(ContentReview.comments),
            selectinload(ContentReview.revisions),
            selectinload(ContentReview.analysis_runs),
        )
        .filter(ContentReview.id == review_id)
        .first()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    return review


@router.get("")
def list_reviews(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    review_status: str = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    query = db.query(ContentReview)
    if review_status:
        if review_status not in {"pending", "in_review", "approved", "changes_requested"}:
            raise HTTPException(status_code=422, detail="Unsupported review status.")
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
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/{review_id}")
def get_review(
    review_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    return review_payload(_get_review(db, review_id))

@router.get("/{review_id}/activity")
def get_review_activity(
    review_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("admin", "reviewer", "contributor")),
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
    reviewer: User = Depends(require_roles("admin", "reviewer")),
):
    review = _get_review(db, review_id)
    record_status_change(db, review, payload.status, reviewer.display_name)
    record_activity(
        db,
        review.id,
        "status_changed",
        actor=reviewer.display_name,
        details={"status": payload.status},
    )
    db.commit()
    db.refresh(review)
    serialized = review_payload(_get_review(db, review_id))
    await collaboration_hub.broadcast(
        review_id,
        {"type": "status_changed", "payload": {"status": payload.status, "reviewer": reviewer.display_name}},
    )
    return serialized


@router.post("/{review_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    review_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    author: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    _get_review(db, review_id)
    comment = ReviewComment(
        review_id=review_id,
        comment=payload.comment,
        author=author.display_name,
    )
    db.add(comment)
    db.flush()
    record_activity(
        db,
        review_id,
        "comment_added",
        actor=author.display_name,
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
        review_id, {"type": "comment_created", "payload": result}
    )
    return result


@router.post("/{review_id}/revisions", status_code=status.HTTP_201_CREATED)
async def add_revision(
    review_id: int,
    payload: RevisionCreate,
    db: Session = Depends(get_db),
    author: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    review = _get_review(db, review_id)
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
        actor=author.display_name,
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
        review_id, {"type": "revision_created", "payload": result}
    )
    return result


@router.post("/{review_id}/reanalyze")
async def reanalyze_revision(
    review_id: int,
    payload: RevisionCreate,
    db: Session = Depends(get_db),
    author: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    if len(payload.content.encode("utf-8")) > MAX_CONTENT_LENGTH:
        raise HTTPException(
            status_code=413,
            detail="Content exceeds the configured maximum length.",
        )
    review = _get_review(db, review_id)
    if payload.content == review.content:
        raise HTTPException(
            status_code=422,
            detail="The revision must differ from the current review content.",
        )

    guideline_ids = review.guideline_ids or []
    guidelines = (
        db.query(BrandGuideline)
        .filter(BrandGuideline.id.in_(guideline_ids))
        .all()
        if guideline_ids
        else []
    )
    sources_query = db.query(SourceDocument).filter(
        SourceDocument.approval_status == "approved"
    )
    if guideline_ids:
        sources_query = sources_query.filter(
            (SourceDocument.guideline_id.is_(None))
            | (SourceDocument.guideline_id.in_(guideline_ids))
        )
    sources = sources_query.all()

    claim_candidates = list(
        dict.fromkeys(
            factual_claim_excerpts(payload.content)
            + [
                str(finding["matched_text"])
                for finding in check_promotional_claims(payload.content)
                if finding.get("matched_text")
            ]
        )
    )
    evidence_by_claim = {}
    evidence_matches = []
    evidence_retrieval_method = retrieval_method()
    warnings = []
    embedding_failed = False
    for claim in claim_candidates[:20]:
        if embedding_failed:
            matches = retrieve_lexical_evidence(claim, sources)
            evidence_retrieval_method = "bm25_lexical_fallback"
        else:
            try:
                matches, evidence_retrieval_method = await retrieve_evidence(
                    claim, sources, db
                )
            except EmbeddingProviderError as exc:
                embedding_failed = True
                matches = retrieve_lexical_evidence(claim, sources)
                evidence_retrieval_method = "bm25_lexical_fallback"
                warnings.append(
                    "Embedding retrieval failed; lexical evidence retrieval was used. {}".format(
                        str(exc)
                    )
                )
        evidence_by_claim[claim.casefold()] = matches
        for match in matches:
            if not any(
                item.get("id") == match.get("id")
                and item.get("excerpt") == match.get("excerpt")
                for item in evidence_matches
            ):
                evidence_matches.append(match)

    findings = analyze_text(
        payload.content,
        guidelines,
        evidence_matches=evidence_matches,
        evidence_by_claim=evidence_by_claim,
    )
    for finding in findings:
        if finding.get("category") not in {"factual_claim", "unsupported_claim"}:
            continue
        claim = str(finding.get("matched_text") or "").strip()
        claim_evidence = evidence_by_claim.get(claim.casefold(), [])
        if not claim_evidence:
            candidate = next(
                (
                    item
                    for item in claim_candidates
                    if claim
                    and (
                        claim.casefold() in item.casefold()
                        or item.casefold() in claim.casefold()
                    )
                ),
                None,
            )
            if candidate:
                claim_evidence = evidence_by_claim.get(candidate.casefold(), [])
        verified = verification_fields(claim, claim_evidence)
        finding.update(verified)
        finding["confidence"] = verified["verification_confidence"]
        finding["explanation"] = "{} {}".format(
            finding["explanation"], verified["verification_explanation"]
        )

    if not review.analysis_runs:
        previous_findings = [finding_payload(item) for item in review.findings]
        db.add(
            ReviewAnalysisRun(
                review_id=review.id,
                content=review.content,
                findings=previous_findings,
                analysis_engine="historical",
                evidence_retrieval_method=None,
                warnings=[],
                created_by_id=None,
            )
        )

    revision = ReviewRevision(
        review_id=review.id,
        content=payload.content,
        title=payload.title or "Revision with re-analysis",
    )
    db.add(revision)
    db.flush()
    review.content = payload.content
    review.analysis_timestamp = datetime.now(timezone.utc)
    review.status = "pending"
    review.reviewer = None
    for old_finding in list(review.findings):
        db.delete(old_finding)
    db.flush()

    new_findings = []
    for item in findings:
        model = ReviewFinding(
            review_id=review.id,
            guideline_id=item.get("guideline_id"),
            category=item["category"],
            severity=item["severity"],
            title=item["title"],
            explanation=item["explanation"],
            matched_text=item.get("matched_text"),
            suggestion=item.get("suggestion"),
            source=item.get("source"),
            confidence=item.get("confidence"),
            review_status="pending",
            metadata_json={
                key: item[key]
                for key in (
                    "claim",
                    "verification_status",
                    "citations",
                    "verification_explanation",
                    "verification_confidence",
                )
                if key in item
            },
        )
        db.add(model)
        new_findings.append(model)
    db.flush()

    finding_snapshots = [finding_payload(item) for item in new_findings]
    db.add(
        ReviewAnalysisRun(
            review_id=review.id,
            content=payload.content,
            findings=finding_snapshots,
            analysis_engine="rules",
            evidence_retrieval_method=evidence_retrieval_method,
            warnings=warnings,
            created_by_id=author.id,
        )
    )
    record_activity(
        db,
        review.id,
        "revision_reanalyzed",
        actor=author.display_name,
        details={
            "revision_id": revision.id,
            "issue_count": len(findings),
            "analysis_engine": "rules",
            "evidence_retrieval_method": evidence_retrieval_method,
            "warnings": warnings,
        },
    )
    db.commit()
    await collaboration_hub.broadcast(
        review_id,
        {
            "type": "revision_created",
            "payload": {
                "id": revision.id,
                "content": revision.content,
                "title": revision.title,
                "summary": revision.title,
                "created_at": revision.created_at,
            },
        },
    )
    serialized = review_payload(_get_review(db, review_id))
    return serialized


@router.websocket("/{review_id}/collaboration")
async def review_collaboration(websocket: WebSocket, review_id: int, db: Session = Depends(get_db)):
    review = db.get(ContentReview, review_id)
    if review is None:
        await websocket.close(code=4404, reason="Review not found.")
        return
    from app.config import AUTH_COOKIE_NAME

    if websocket.headers.get("origin") not in CORS_ORIGINS:
        await websocket.close(code=4403, reason="Origin is not allowed.")
        return
    user = authenticate_token(db, websocket.cookies.get(AUTH_COOKIE_NAME))
    if user is None:
        await websocket.close(code=4401, reason="Sign in to collaborate.")
        return
    if user.must_change_password:
        await websocket.close(code=4403, reason="Change your temporary password first.")
        return
    await collaboration_hub.connect(review_id, websocket, user.id)
    try:
        await collaboration_hub.broadcast(
            review_id,
            {"type": "presence", "payload": {"event": "joined", "review_id": review_id}},
        )
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=60)
            except asyncio.TimeoutError:
                active_user = authenticate_token(
                    db, websocket.cookies.get(AUTH_COOKIE_NAME)
                )
                if active_user is None or active_user.must_change_password:
                    await websocket.close(code=4401, reason="Workspace session expired.")
                    break
                continue
            if len(raw.encode("utf-8")) > 2048:
                await websocket.send_json({"type": "error", "message": "Message too large."})
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Send valid JSON."})
                continue
            if not isinstance(message, dict) or message.get("type") not in {"typing", "presence"}:
                if (
                    isinstance(message, dict)
                    and message.get("type") == "draft_changed"
                    and isinstance(message.get("content"), str)
                    and len(message["content"].encode("utf-8")) <= 100_000
                ):
                    await collaboration_hub.broadcast(
                        review_id,
                        {
                            "type": "draft_changed",
                            "payload": {
                                "content": message["content"],
                                "user": user.display_name,
                            },
                        },
                    )
                    continue
                await websocket.send_json(
                    {"type": "error", "message": "Unsupported collaboration event or invalid draft size."}
                )
                continue
            payload = {
                "type": message["type"],
                "payload": {
                    "user": user.display_name,
                    "active": bool(message.get("active", True)),
                },
            }
            await collaboration_hub.broadcast(review_id, payload)
    except WebSocketDisconnect:
        pass
    finally:
        await collaboration_hub.disconnect(review_id, websocket, user.id)
