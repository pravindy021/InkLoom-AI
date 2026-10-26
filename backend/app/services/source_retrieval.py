import re
from datetime import date
from typing import Dict, List, Sequence

from app.models.source_document import SourceDocument

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9'-]{1,}", re.IGNORECASE)
STOP_WORDS = {
    "about", "after", "again", "against", "also", "among", "because", "been",
    "before", "being", "between", "both", "could", "does", "during", "each",
    "from", "have", "into", "more", "most", "other", "over", "same", "such",
    "than", "that", "their", "them", "then", "there", "these", "they", "this",
    "those", "through", "under", "very", "were", "what", "when", "where", "which",
    "while", "with", "would", "your",
}


def tokenize(value: str) -> set:
    return {
        token.lower()
        for token in TOKEN_PATTERN.findall(value)
        if token.lower() not in STOP_WORDS and len(token) > 2
    }


def retrieve_evidence(
    query: str, sources: Sequence[SourceDocument], limit: int = 5
) -> List[Dict[str, object]]:
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    candidates = []
    today = date.today()
    for source in sources:
        text_tokens = tokenize(source.content)
        overlap = query_tokens.intersection(text_tokens)
        if not overlap:
            continue
        score = len(overlap) / max(1, len(query_tokens))
        if score < 0.18:
            continue
        expiry_date = source.expiry_date
        fresh = expiry_date is None or expiry_date >= today
        freshness = "current" if fresh else "expired"
        matched_tokens = sorted(overlap)
        candidates.append(
            {
                "id": source.id,
                "name": source.name,
                "url": source.url,
                "guideline_id": source.guideline_id,
                "source_date": source.source_date.isoformat() if source.source_date else None,
                "expiry_date": expiry_date.isoformat() if expiry_date else None,
                "freshness": freshness,
                "relevance_score": round(score, 3),
                "matched_terms": matched_tokens[:8],
                "excerpt": _excerpt(source.content, matched_tokens),
                "verification": "candidate_evidence_requires_human_review",
            }
        )
    return sorted(
        candidates,
        key=lambda item: (
            item["freshness"] != "current",
            -float(item["relevance_score"]),
        ),
    )[:limit]


def _excerpt(content: str, terms: Sequence[str], width: int = 360) -> str:
    lower = content.lower()
    positions = [lower.find(term) for term in terms if lower.find(term) >= 0]
    start = max(0, (min(positions) if positions else 0) - 100)
    end = min(len(content), start + width)
    excerpt = content[start:end].strip()
    if start:
        excerpt = "…{}".format(excerpt)
    if end < len(content):
        excerpt = "{}…".format(excerpt)
    return excerpt
