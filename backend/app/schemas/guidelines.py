from datetime import datetime
from typing import List, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApprovedSource(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    url: Optional[str] = Field(default=None, max_length=2048)
    reference: Optional[str] = Field(default=None, max_length=1000)
    source_date: Optional[str] = Field(default=None, max_length=40)
    expiry_date: Optional[str] = Field(default=None, max_length=40)

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("source URL must be an HTTP or HTTPS URL without credentials")
        return value


class GuidelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=4000)
    severity: str = "medium"
    prohibited_terms: List[str] = Field(default_factory=list, max_length=100)
    preferred_terms: List[str] = Field(default_factory=list, max_length=100)
    approved_sources: List[ApprovedSource] = Field(default_factory=list, max_length=50)

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        value = value.lower()
        if value not in {"low", "medium", "high", "critical"}:
            raise ValueError("severity must be low, medium, high, or critical")
        return value

    @field_validator("name", "category", "description")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("prohibited_terms", "preferred_terms")
    @classmethod
    def trim_terms(cls, values: List[str]) -> List[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 120 for value in cleaned):
            raise ValueError("terms cannot exceed 120 characters")
        return cleaned


class GuidelineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    description: str
    severity: str
    prohibited_terms: List[str]
    preferred_terms: List[str]
    approved_sources: List[dict]
    status: str
    is_seed: bool
    created_at: datetime
