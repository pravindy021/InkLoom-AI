import re
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence

from app.models.brand_guideline import BrandGuideline
from app.services.claim_checker import (
    check_promotional_claims,
    factual_claim_excerpt,
    factual_claim_excerpts,
)
from app.services.suggestion_engine import (
    claim_suggestion,
    factual_suggestion,
    terminology_suggestion,
)


def _term_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term.strip())
    if not escaped:
        return re.compile(r"(?!x)x")
    if term[0].isalnum() or term[0] == "_":
        escaped = r"\b" + escaped
    if term[-1].isalnum() or term[-1] == "_":
        escaped += r"\b"
    return re.compile(escaped, re.IGNORECASE)


def _source_is_expired(source: dict) -> bool:
    expiry = source.get("expiry_date")
    if not expiry:
        return False
    try:
        return date.fromisoformat(str(expiry)[:10]) < date.today()
    except ValueError:
        return False


def _factual_guideline(
    text: str,
    guidelines: Sequence[BrandGuideline],
    evidence_matches: Optional[Sequence[dict]] = None,
    excerpt_override: Optional[str] = None,
) -> Optional[tuple]:
    excerpt = excerpt_override or factual_claim_excerpt(text)
    if not excerpt:
        return None
    evidence_matches = evidence_matches or []
    if evidence_matches:
        current_matches = [
            item for item in evidence_matches if item.get("freshness") == "current"
        ]
        undated_matches = [
            item for item in evidence_matches if item.get("freshness") == "no_expiry_date"
        ]
        unknown_date_matches = [
            item for item in evidence_matches if item.get("freshness") == "unknown"
        ]
        selected = (
            current_matches
            or undated_matches
            or unknown_date_matches
            or list(evidence_matches)
        )
        source_names = ", ".join(str(item.get("name") or "approved source") for item in selected)
        guideline_ids = [
            item.get("guideline_id")
            for item in selected
            if item.get("guideline_id") is not None
        ]
        if current_matches or undated_matches:
            freshness_note = (
                "A current approved source excerpt matched this statement"
                if current_matches
                else "An approved source excerpt with no recorded expiry date matched this statement"
            )
            return (
                excerpt,
                "{} ({}). Compare exact scope and context before publication; "
                "this match is not verification.".format(freshness_note, source_names),
                guideline_ids[0] if guideline_ids else None,
                source_names,
            )
        if unknown_date_matches:
            return (
                excerpt,
                "A result from a configured trusted source may be relevant ({}). "
                "Confirm the source and claim context before publication."
                .format(source_names),
                guideline_ids[0] if guideline_ids else None,
                source_names,
            )
        return (
            excerpt,
            "Only expired approved source material matched this statement ({}). "
            "Verify against a current source before publication."
            .format(source_names),
            guideline_ids[0] if guideline_ids else None,
            source_names,
        )
    relevant = [
        item
        for item in guidelines
        if any(word in item.category.lower() for word in ("fact", "evidence", "source"))
    ]
    if not relevant:
        relevant = [item for item in guidelines if "claim" in item.category.lower()]
    if not relevant:
        return (
            excerpt,
            "No approved evidence guideline was selected for this potentially factual statement.",
            None,
            "Unverified factual statement heuristic",
        )
    for item in relevant:
        expired = [source for source in item.approved_sources or [] if _source_is_expired(source)]
        active = [
            source
            for source in item.approved_sources or []
            if source.get("name") and not _source_is_expired(source)
        ]
        if expired and not active:
            source_names = ", ".join(source.get("name", "source") for source in expired)
            return (
                excerpt,
                "The configured evidence source may have expired ({}); verify the statement against a current source."
                .format(source_names),
                item.id,
                item.name,
            )
        if not active:
            return (
                excerpt,
                "No current approved evidence source is configured for this guideline.",
                item.id,
                item.name,
            )
    names = ", ".join(item.name for item in relevant)
    return (
        excerpt,
        "Approved evidence references are configured ({}), but no matching approved-source excerpt was found for this statement."
        .format(names),
        relevant[0].id,
        relevant[0].name,
    )


def analyze_text(
    text: str,
    guidelines: Sequence[BrandGuideline],
    image_attached: bool = False,
    alt_text: Optional[str] = None,
    evidence_matches: Optional[Sequence[dict]] = None,
    evidence_by_claim: Optional[Dict[str, Sequence[dict]]] = None,
) -> List[Dict[str, object]]:
    findings: List[Dict[str, object]] = []

    for guideline in guidelines:
        prohibited = guideline.prohibited_terms or []
        preferred = guideline.preferred_terms or []
        for index, term in enumerate(prohibited):
            if not isinstance(term, str) or not term.strip():
                continue
            preferred_term = preferred[index] if index < len(preferred) else None
            for match in _term_pattern(term).finditer(text):
                findings.append(
                    {
                        "category": "terminology",
                        "severity": guideline.severity,
                        "title": "Prohibited or non-preferred terminology",
                        "explanation": (
                            "This wording matches a term prohibited by the configured guideline: {}."
                        ).format(guideline.name),
                        "matched_text": match.group(0),
                        "suggestion": terminology_suggestion(match.group(0), preferred_term),
                        "source": guideline.name,
                        "guideline": guideline.name,
                        "guideline_id": guideline.id,
                        "confidence": 0.96,
                    }
                )

    claim_guidelines = [
        item for item in guidelines if "claim" in item.category.lower()
    ]
    claim_guideline = claim_guidelines[0] if claim_guidelines else None
    findings.extend(check_promotional_claims(text))
    for finding in findings:
        if finding["category"] == "unsupported_claim":
            finding["suggestion"] = claim_suggestion(str(finding["matched_text"]))
            if claim_guideline:
                finding["source"] = claim_guideline.name
                finding["guideline"] = claim_guideline.name
                finding["guideline_id"] = claim_guideline.id

    for excerpt in factual_claim_excerpts(text):
        if any(
            finding["category"] == "unsupported_claim"
            and finding["matched_text"]
            and (
                excerpt.casefold() in str(finding["matched_text"]).casefold()
                or str(finding["matched_text"]).casefold() in excerpt.casefold()
            )
            for finding in findings
        ):
            continue
        if evidence_by_claim is not None:
            claim_evidence = evidence_by_claim.get(excerpt.casefold(), [])
        else:
            claim_evidence = evidence_matches
        factual = _factual_guideline(
            text,
            guidelines,
            claim_evidence,
            excerpt_override=excerpt,
        )
        if factual:
            _excerpt, explanation, guideline_id, source = factual
            findings.append(
                {
                    "category": "factual_claim",
                    "severity": "medium",
                    "title": "Verify factual statement",
                    "explanation": explanation,
                    "matched_text": excerpt,
                    "suggestion": factual_suggestion(),
                    "source": source,
                    "guideline": source,
                    "guideline_id": guideline_id,
                    "confidence": 0.62,
                }
            )

    click_here = re.search(r"\bclick here\b", text, re.IGNORECASE)
    if click_here:
        findings.append(
            {
                "category": "accessibility",
                "severity": "low",
                "title": "Non-descriptive link wording",
                "explanation": "“Click here” does not describe the destination and can be less useful to assistive-technology users.",
                "matched_text": click_here.group(0),
                "suggestion": "Replace it with a concise link label that describes the destination or action.",
                "source": "Basic accessibility heuristic (not a WCAG audit)",
                "guideline": None,
                "guideline_id": None,
                "confidence": 0.82,
            }
        )

    if image_attached and not (alt_text or "").strip():
        findings.append(
            {
                "category": "accessibility",
                "severity": "medium",
                "title": "Image alternative text not provided",
                "explanation": "No alternative text was supplied for the uploaded image, so its meaning may not be available to screen-reader users.",
                "matched_text": None,
                "suggestion": "Add concise alternative text describing the image's relevant content or purpose.",
                "source": "Basic image accessibility check (not a WCAG audit)",
                "guideline": None,
                "guideline_id": None,
                "confidence": 0.9,
            }
        )

    return findings
