from datetime import date, datetime
from typing import List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceApprovalUpdate(BaseModel):
    status: Literal["approved", "rejected"]
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def trim_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=200_000)
    guideline_id: Optional[int] = None
    url: Optional[str] = Field(default=None, max_length=2048)
    source_date: Optional[date] = None
    expiry_date: Optional[date] = None

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("source URL must be an HTTP or HTTPS URL without credentials")
        return value

    @field_validator("name", "content")
    @classmethod
    def strip_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @model_validator(mode="after")
    def check_dates(self):
        if self.source_date and self.expiry_date and self.expiry_date < self.source_date:
            raise ValueError("expiry_date cannot precede source_date")
        return self


class SourceApprovalHistoryRead(BaseModel):
    status: Literal["approved", "rejected"]
    reviewer: Optional[str]
    note: Optional[str]
    created_at: datetime


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    content: str
    guideline_id: Optional[int]
    url: Optional[str]
    source_date: Optional[date]
    expiry_date: Optional[date]
    approval_status: Literal["pending", "approved", "rejected"]
    reviewed_by_id: Optional[int]
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]
    review_note: Optional[str]
    approval_history: List[SourceApprovalHistoryRead] = Field(default_factory=list)
    created_at: datetime
