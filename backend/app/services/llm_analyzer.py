import json
from typing import Dict, List, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import LLM_API_BASE_URL, LLM_API_KEY, LLM_MODEL
from app.models.brand_guideline import BrandGuideline


class LLMProviderError(RuntimeError):
    pass


class LLMFinding(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    severity: str
    title: str = Field(min_length=1, max_length=200)
    explanation: str = Field(min_length=1, max_length=2000)
    matched_text: Optional[str] = Field(default=None, max_length=1000)
    suggestion: Optional[str] = Field(default=None, max_length=2000)
    guideline: Optional[str] = Field(default=None, max_length=240)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)

    def validate_severity(self) -> None:
        if self.severity.lower() not in {"low", "medium", "high", "critical"}:
            raise ValueError("LLM returned unsupported severity.")


def llm_enabled() -> bool:
    return bool(LLM_API_BASE_URL and LLM_API_KEY and LLM_MODEL)


async def analyze_with_llm(
    content: str,
    guidelines: List[BrandGuideline],
    evidence: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    rule_context = [
        {
            "name": item.name,
            "category": item.category,
            "description": item.description,
            "severity": item.severity,
            "prohibited_terms": item.prohibited_terms or [],
            "preferred_terms": item.preferred_terms or [],
        }
        for item in guidelines
    ]
    evidence_context = [
        {"name": item.get("name"), "excerpt": item.get("excerpt")}
        for item in evidence[:5]
    ]
    prompt = (
        "Review the submitted content against the supplied brand rules. Identify only "
        "specific, actionable issues. Preserve the author's intent. Do not claim any "
        "factual statement is verified or false; approved excerpts are candidate evidence "
        "only. Return strict JSON with one property, findings, an array whose items have "
        "category, severity (low|medium|high|critical), title, explanation, matched_text "
        "(exact substring of content or null), suggestion, guideline (name or null), and "
        "confidence (0..1 or null). Do not include markdown.\n\n"
        "RULES:\n{}\n\nCANDIDATE EVIDENCE (not authoritative verification):\n{}\n\n"
        "CONTENT:\n{}".format(
            json.dumps(rule_context, ensure_ascii=False),
            json.dumps(evidence_context, ensure_ascii=False),
            content,
        )
    )
    endpoint = "{}/chat/completions".format(LLM_API_BASE_URL)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0)) as client:
            response = await client.post(
                endpoint,
                headers={"Authorization": "Bearer {}".format(LLM_API_KEY)},
                json={
                    "model": LLM_MODEL,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a cautious brand-compliance reviewer. Findings are advisory.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
            response_body = response.json()
            raw_content = response_body["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        detail = (
            "Configured LLM provider rejected the request (HTTP {}).".format(status_code)
            if status_code
            else "Configured LLM provider request failed ({}).".format(type(exc).__name__)
        )
        raise LLMProviderError(detail) from exc

    try:
        decoded = json.loads(raw_content)
        raw_findings = decoded.get("findings")
        if not isinstance(raw_findings, list):
            raise ValueError("Provider response must contain a findings array.")
        validated = []
        guidelines_by_name = {item.name.casefold(): item for item in guidelines}
        for raw in raw_findings:
            finding = LLMFinding.model_validate(raw)
            finding.validate_severity()
            if finding.matched_text and finding.matched_text not in content:
                raise ValueError("Provider finding matched_text is not in submitted content.")
            guideline = guidelines_by_name.get((finding.guideline or "").casefold())
            validated.append(
                {
                    **finding.model_dump(),
                    "severity": finding.severity.lower(),
                    "source": guideline.name if guideline else "Configured LLM advisory",
                    "guideline_id": guideline.id if guideline else None,
                }
            )
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise LLMProviderError(
            "Configured LLM provider returned an invalid findings response."
        ) from exc
    return validated
