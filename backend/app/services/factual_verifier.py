import re
from typing import Dict, List, Sequence, Tuple
from urllib.parse import urlsplit

import httpx

from app.config import FACT_CHECK_API_KEY, FACT_CHECK_ENABLED, TRUSTED_SOURCE_DOMAINS

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_EXTERNAL_CLAIMS = 5
MAX_EXTERNAL_RESULTS = 5
MAX_EXTERNAL_QUERY_LENGTH = 500
WORD_PATTERN = re.compile(r"[a-z][a-z'-]{2,}", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"(?<!\w)(?:\$[\d,]+|\d+(?:\.\d+)?\s*%?)(?!\w)")
STOP_WORDS = {
    "about", "after", "also", "and", "are", "for", "from", "has", "have",
    "into", "its", "more", "our", "than", "that", "the", "their", "this",
    "was", "were", "with",
}


class ExternalSearchError(RuntimeError):
    pass


def _trusted_host(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            return False
        hostname = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in TRUSTED_SOURCE_DOMAINS
    )


async def search_trusted_sources(claim: str) -> List[Dict[str, object]]:
    if not FACT_CHECK_ENABLED or not FACT_CHECK_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0),
            follow_redirects=False,
        ) as client:
            response = await client.get(
                BRAVE_SEARCH_URL,
                headers={"X-Subscription-Token": FACT_CHECK_API_KEY},
                params={
                    "q": claim[:MAX_EXTERNAL_QUERY_LENGTH],
                    "count": MAX_EXTERNAL_RESULTS,
                },
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        reason = "HTTP {}".format(status_code) if status_code else type(exc).__name__
        raise ExternalSearchError(
            "Configured external search provider failed ({}).".format(reason)
        ) from exc

    web = body.get("web") if isinstance(body, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    if not isinstance(results, list):
        raise ExternalSearchError("Configured external search provider returned an invalid response.")

    trusted = []
    for result in results[:MAX_EXTERNAL_RESULTS]:
        if not isinstance(result, dict):
            continue
        url = result.get("url")
        title = result.get("title")
        excerpt = result.get("description")
        if (
            not isinstance(url, str)
            or not _trusted_host(url)
            or not isinstance(title, str)
            or not isinstance(excerpt, str)
            or not title.strip()
            or not excerpt.strip()
        ):
            continue
        trusted.append(
            {
                "name": title.strip()[:240],
                "url": url,
                "excerpt": excerpt.strip()[:1200],
                "freshness": "unknown",
                "source_type": "external_trusted_source",
                "verification": "candidate_evidence_requires_human_review",
            }
        )
    return trusted


def _meaningful_words(value: str) -> set:
    return {
        word.lower()
        for word in WORD_PATTERN.findall(value)
        if word.lower() not in STOP_WORDS
    }


def _numbers(value: str) -> Tuple[str, ...]:
    return tuple(
        re.sub(r"\s+", "", match.group(0)).replace(",", "")
        for match in NUMBER_PATTERN.finditer(value)
    )


def _sentences(value: str) -> List[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", value)
        if sentence.strip()
    ]


def classify_claim(
    claim: str, evidence: Sequence[Dict[str, object]]
) -> Tuple[str, float, List[Dict[str, object]]]:
    claim_words = _meaningful_words(claim)
    claim_numbers = _numbers(claim)
    if not claim_words:
        return "unverified", 0.2, []

    supported = []
    contradicted = []
    for source in evidence:
        if source.get("freshness") == "expired":
            continue
        excerpt = str(source.get("excerpt") or "")
        for sentence in _sentences(excerpt):
            source_words = _meaningful_words(sentence)
            if not source_words:
                continue
            overlap = len(claim_words & source_words) / len(claim_words)
            sentence_numbers = _numbers(sentence)
            if overlap >= 0.8 and claim_numbers and sentence_numbers:
                if claim_numbers == sentence_numbers:
                    supported.append(source)
                elif len(claim_numbers) == len(sentence_numbers):
                    contradicted.append(source)
            elif overlap == 1 and not claim_numbers:
                supported.append(source)
    if supported:
        return "verified", 0.9, supported[:3]
    if contradicted:
        return "contradicted", 0.8, contradicted[:3]
    return "unverified", 0.25, []


def verification_fields(
    claim: str,
    evidence: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    status, confidence, citations = classify_claim(claim, evidence)
    explanations = {
        "verified": "A configured source contains matching claim details. Confirm scope, date, and context before publication.",
        "contradicted": "A configured source contains a conflicting value for this claim. Check that the source is current and applies to the same scope.",
        "unverified": "No sufficiently clear supporting or conflicting statement was found. Lack of evidence is not proof that this claim is false.",
    }
    return {
        "claim": claim,
        "verification_status": status,
        "citations": citations,
        "verification_explanation": explanations[status],
        "verification_confidence": confidence,
    }
