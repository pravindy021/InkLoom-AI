import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from app.config import (
    FACT_CHECK_ENABLED,
    FACT_CHECK_PROVIDER,
    MAX_CONTENT_LENGTH,
    MAX_UPLOAD_SIZE,
    OCR_ENABLED,
    TRUSTED_SOURCE_DOMAINS,
)
from app.database import get_db
from app.models.brand_guideline import BrandGuideline
from app.models.content_review import ContentReview, ReviewAnalysisRun, ReviewFinding
from app.models.source_document import SourceDocument
from app.models.user import User
from app.schemas.analysis import AnalysisRequest
from app.services.activity_service import record_activity
from app.services.image_analyzer import (
    ImageAnalysisConfigurationError,
    inspect_image,
)
from app.services.review_service import finding_payload
from app.services.claim_checker import check_promotional_claims, factual_claim_excerpts
from app.services.factual_verifier import (
    ExternalSearchError,
    MAX_EXTERNAL_CLAIMS,
    search_trusted_sources,
    verification_fields,
)
from app.services.source_retrieval import (
    EmbeddingProviderError,
    retrieve_evidence,
    retrieve_lexical_evidence,
    retrieval_method,
)
from app.services.llm_analyzer import LLMProviderError, analyze_with_llm, llm_enabled
from app.services.text_analyzer import analyze_text
from app.services.auth_service import require_roles

router = APIRouter(prefix="/api", tags=["analysis"])
MAX_LOCAL_CLAIMS = 20


async def _parse_request(request: Request):
    content_type = request.headers.get("content-type", "").lower()
    raw_content_length = request.headers.get("content-length")
    if raw_content_length:
        try:
            request_length = int(raw_content_length)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.")
        maximum_request_length = (
            MAX_CONTENT_LENGTH + 16_384
            if "application/json" in content_type
            else MAX_CONTENT_LENGTH + MAX_UPLOAD_SIZE + 262_144
        )
        if request_length > maximum_request_length:
            raise HTTPException(status_code=413, detail="Request exceeds the configured size limit.")

    image_bytes: Optional[bytes] = None
    if "application/json" in content_type:
        try:
            raw = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="Request body must be valid JSON.")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail="JSON request body must be an object.")
        payload = raw
    elif "multipart/form-data" in content_type:
        try:
            form = await request.form()
        except (MultiPartException, ValueError, OSError):
            raise HTTPException(status_code=400, detail="Could not parse multipart form data.")
        raw_guideline_ids = form.get("guideline_ids", "[]")
        guideline_ids = _parse_id_list(raw_guideline_ids, "guideline_ids")
        payload = {
            "title": form.get("title"),
            "content": form.get("content", ""),
            "content_type": form.get("content_type") or "text",
            "guideline_ids": guideline_ids or [],
            "source_ids": _parse_id_list(form.get("source_ids", "[]"), "source_ids"),
            "alt_text": form.get("alt_text"),
            "allow_external_verification": form.get("allow_external_verification", "false"),
        }
        uploaded = form.get("file")
        if uploaded is not None:
            if not isinstance(uploaded, UploadFile):
                raise HTTPException(status_code=422, detail="file must be an uploaded image.")
            if uploaded.size is not None and uploaded.size > MAX_UPLOAD_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail="Image exceeds the configured maximum upload size.",
                )
            image_bytes = await uploaded.read(MAX_UPLOAD_SIZE + 1)
            if len(image_bytes) > MAX_UPLOAD_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail="Image exceeds the configured maximum upload size.",
                )
            if not image_bytes:
                raise HTTPException(status_code=400, detail="Uploaded image is empty.")
    else:
        raise HTTPException(
            status_code=415,
            detail="Use application/json or multipart/form-data.",
        )

    if len(str(payload.get("content", "")).encode("utf-8")) > MAX_CONTENT_LENGTH:
        raise HTTPException(
            status_code=413,
            detail="Content exceeds the configured maximum length.",
        )
    try:
        validated = AnalysisRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_context=False))
    return validated, image_bytes


def _parse_id_list(value, field_name: str):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="{} must be a JSON array.".format(field_name))
    if not isinstance(parsed, list) or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in parsed
    ):
        raise HTTPException(status_code=422, detail="{} must contain positive integer IDs.".format(field_name))
    return parsed


@router.post("/analyze")
async def analyze_content(
    request: Request,
    db: Session = Depends(get_db),
    analyst: User = Depends(require_roles("admin", "reviewer", "contributor")),
):
    payload, image_bytes = await _parse_request(request)
    if payload.guideline_ids:
        guidelines = (
            db.query(BrandGuideline)
            .filter(BrandGuideline.id.in_(payload.guideline_ids))
            .all()
        )
        found_ids = {item.id for item in guidelines}
        missing_ids = sorted(set(payload.guideline_ids) - found_ids)
        if missing_ids:
            raise HTTPException(
                status_code=422,
                detail="Unknown guideline id(s): {}.".format(", ".join(map(str, missing_ids))),
            )
    else:
        guidelines = db.query(BrandGuideline).all()

    source_query = db.query(SourceDocument).filter(
        SourceDocument.approval_status == "approved"
    )
    if payload.source_ids:
        source_query = source_query.filter(SourceDocument.id.in_(payload.source_ids))
    elif payload.guideline_ids:
        source_query = source_query.filter(
            (SourceDocument.guideline_id.is_(None))
            | (SourceDocument.guideline_id.in_(payload.guideline_ids))
        )
    sources = source_query.all()
    if payload.source_ids:
        found_source_ids = {item.id for item in sources}
        missing_source_ids = sorted(set(payload.source_ids) - found_source_ids)
        if missing_source_ids:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Unknown or unapproved source id(s): {}."
                    .format(", ".join(map(str, missing_source_ids)))
                ),
            )
    claim_candidates = factual_claim_excerpts(payload.content) + [
        str(item["matched_text"])
        for item in check_promotional_claims(payload.content)
        if item.get("matched_text")
    ]
    claim_candidates = list(dict.fromkeys(claim_candidates))
    evidence_by_claim = {}
    evidence_matches = []
    evidence_retrieval_method = retrieval_method()
    embedding_provider_failed = False
    provider_warnings = []
    external_failure = False
    external_claims_searched = 0
    external_claims_attempted = 0
    external_search_candidates = (
        min(len(claim_candidates), MAX_EXTERNAL_CLAIMS)
        if payload.allow_external_verification and FACT_CHECK_ENABLED
        else 0
    )
    for index, claim in enumerate(claim_candidates[:MAX_LOCAL_CLAIMS]):
        if embedding_provider_failed:
            local_matches = retrieve_lexical_evidence(claim, sources)
            evidence_retrieval_method = "bm25_lexical_fallback"
        else:
            try:
                local_matches, evidence_retrieval_method = await retrieve_evidence(
                    claim, sources, db
                )
            except EmbeddingProviderError as exc:
                embedding_provider_failed = True
                provider_warnings.append(
                    "Embedding retrieval failed; lexical evidence retrieval was used. {}".format(
                        str(exc)
                    )
                )
                local_matches = retrieve_lexical_evidence(claim, sources)
                evidence_retrieval_method = "bm25_lexical_fallback"
        claim_evidence = list(local_matches)
        if (
            payload.allow_external_verification
            and FACT_CHECK_ENABLED
            and index < MAX_EXTERNAL_CLAIMS
        ):
            external_claims_attempted += 1
            try:
                claim_evidence.extend(await search_trusted_sources(claim))
                external_claims_searched += 1
            except ExternalSearchError:
                external_failure = True
        evidence_by_claim[claim.casefold()] = claim_evidence
        for evidence in claim_evidence:
            evidence_key = (
                evidence.get("source_type"),
                evidence.get("id"),
                evidence.get("url"),
                evidence.get("excerpt"),
            )
            if not any(
                (
                    existing.get("source_type"),
                    existing.get("id"),
                    existing.get("url"),
                    existing.get("excerpt"),
                )
                == evidence_key
                for existing in evidence_matches
            ):
                evidence_matches.append(evidence)

    image_info = None
    if image_bytes is not None:
        try:
            image_info = inspect_image(image_bytes, OCR_ENABLED)
        except ImageAnalysisConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    analysis_text = payload.content
    if image_info and image_info.get("extracted_text"):
        analysis_text = "{}\n{}".format(analysis_text, image_info["extracted_text"])

    findings = analyze_text(
        analysis_text,
        guidelines,
        image_attached=image_bytes is not None,
        alt_text=payload.alt_text,
        evidence_matches=evidence_matches,
        evidence_by_claim=evidence_by_claim,
    )
    analysis_engine = "rules"
    if llm_enabled():
        try:
            llm_findings = await analyze_with_llm(payload.content, guidelines, evidence_matches)
        except LLMProviderError as exc:
            provider_warnings.append(
                "Configured LLM analysis failed; deterministic findings are still available. {}".format(
                    str(exc)
                )
            )
        else:
            known = {
                (
                    str(item.get("category", "")).casefold(),
                    str(item.get("matched_text") or "").casefold(),
                )
                for item in findings
            }
            for item in llm_findings:
                key = (
                    str(item.get("category", "")).casefold(),
                    str(item.get("matched_text") or "").casefold(),
                )
                if key not in known:
                    findings.append(item)
                    known.add(key)
            analysis_engine = "rules+configured_llm"
    for finding in findings:
        if finding.get("category") not in {"factual_claim", "unsupported_claim"}:
            continue
        claim = str(finding.get("matched_text") or "").strip()
        claim_evidence = evidence_by_claim.get(claim.casefold(), [])
        if not claim_evidence:
            matching_claim = next(
                (
                    candidate
                    for candidate in claim_candidates
                    if claim
                    and (
                        claim.casefold() in candidate.casefold()
                        or candidate.casefold() in claim.casefold()
                    )
                ),
                None,
            )
            if matching_claim:
                claim_evidence = evidence_by_claim.get(matching_claim.casefold(), [])
        verified = verification_fields(claim, claim_evidence)
        finding.update(verified)
        finding["confidence"] = verified["verification_confidence"]
        finding["explanation"] = "{} {}".format(
            finding["explanation"], verified["verification_explanation"]
        )
    palette_result = image_info.get("palette_comparison") if image_info else None
    if palette_result and palette_result.get("potential_mismatch"):
        findings.append(
            {
                "category": "visual_brand",
                "severity": "medium",
                "title": "Image colours may differ from configured brand palette",
                "explanation": "At least one dominant image colour exceeds the configured approximate RGB distance. Review visually; this heuristic is not a perceptual brand-compliance decision.",
                "matched_text": None,
                "suggestion": "Compare the asset with approved brand references and adjust only if the difference is unintended.",
                "source": "Configured palette RGB-distance heuristic",
                "guideline": None,
                "guideline_id": None,
                "confidence": None,
            }
        )
    asset_similarity = (
        image_info.get("brand_asset_similarity") if image_info else None
    )
    if asset_similarity and asset_similarity.get("potential_mismatch"):
        best_match = max(
            item["similarity_percent"]
            for item in asset_similarity["references"]
        )
        findings.append(
            {
                "category": "visual_brand",
                "severity": "low",
                "title": "Image differs from configured brand asset references",
                "explanation": (
                    "The uploaded image's highest coarse visual similarity to a configured "
                    "reference is {}%, below the configured {}% threshold. This hash heuristic "
                    "does not determine whether the asset is approved or appropriate."
                ).format(best_match, asset_similarity["threshold_percent"]),
                "matched_text": None,
                "suggestion": (
                    "Confirm this asset is an approved variant or compare it with the "
                    "current brand asset library."
                ),
                "source": "Configured brand asset difference-hash comparison",
                "guideline": None,
                "guideline_id": None,
                "confidence": None,
            }
        )
    review = ContentReview(
        title=(payload.title or "").strip() or "Untitled content",
        content=payload.content,
        content_type=payload.content_type,
        status="pending",
        guideline_ids=[item.id for item in guidelines],
    )
    db.add(review)
    db.flush()
    record_activity(
        db,
        review.id,
        "analysis_completed",
        actor=analyst.display_name,
        details={
            "issue_count": len(findings),
            "analysis_engine": analysis_engine,
            "image_attached": image_bytes is not None,
        },
    )
    finding_models: List[ReviewFinding] = []
    for item in findings:
        model = ReviewFinding(
            review_id=review.id,
            guideline_id=item["guideline_id"],
            category=item["category"],
            severity=item["severity"],
            title=item["title"],
            explanation=item["explanation"],
            matched_text=item["matched_text"],
            suggestion=item["suggestion"],
            source=item["source"],
            confidence=item["confidence"],
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
        finding_models.append(model)
    db.flush()
    db.add(
        ReviewAnalysisRun(
            review_id=review.id,
            content=payload.content,
            findings=[finding_payload(item) for item in finding_models],
            analysis_engine=analysis_engine,
            evidence_retrieval_method=evidence_retrieval_method,
            warnings=provider_warnings,
            created_by_id=analyst.id,
        )
    )
    db.commit()
    db.refresh(review)
    for finding in finding_models:
        db.refresh(finding)

    severity_counts = {
        severity: sum(1 for finding in findings if finding["severity"] == severity)
        for severity in ("critical", "high", "medium", "low")
    }
    category_counts = {}
    for finding in findings:
        category = finding["category"]
        category_counts[category] = category_counts.get(category, 0) + 1
    overall_status = "needs_review" if findings else "no_issues_detected"
    return {
        "id": review.id,
        "review_id": review.id,
        "title": review.title,
        "content": review.content,
        "content_type": review.content_type,
        "status": review.status,
        "overall_status": overall_status,
        "total_issues": len(findings),
        "issue_count": len(findings),
        "summary": {
            "total_issues": len(findings),
            "severity_counts": severity_counts,
            "category_counts": category_counts,
        },
        "findings": [finding_payload(item) for item in finding_models],
        "issues": [finding_payload(item) for item in finding_models],
        "retrieved_evidence": evidence_matches,
        "evidence_retrieval_method": evidence_retrieval_method,
        "provider_warnings": provider_warnings,
        "factual_verification": "claim_level_verification_advisory",
        "external_verification": {
            "requested": payload.allow_external_verification,
            "enabled": FACT_CHECK_ENABLED,
            "provider": FACT_CHECK_PROVIDER or None,
            "trusted_source_domains": list(TRUSTED_SOURCE_DOMAINS),
            "status": (
                "not_requested"
                if not payload.allow_external_verification
                else "not_configured"
                if not FACT_CHECK_ENABLED
                else "provider_error"
                if external_failure
                else "partial"
                if payload.allow_external_verification
                and len(claim_candidates) > external_search_candidates
                else "completed"
            ),
            "claims_attempted": external_claims_attempted,
            "claims_searched": external_claims_searched,
            "claims_failed": external_claims_attempted - external_claims_searched,
            "claims_not_externally_searched": (
                max(0, len(claim_candidates) - external_claims_attempted)
                if payload.allow_external_verification
                else 0
            ),
        },
        "analysis_engine": analysis_engine,
        "analyzed_at": datetime.now(timezone.utc),
        "image_analysis": image_info,
    }
