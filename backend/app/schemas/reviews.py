from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.analysis import FindingRead

REVIEW_STATUSES = {"pending", "in_review", "approved", "changes_requested"}


class StatusUpdate(BaseModel):
    status: str
    reviewer: Optional[str] = Field(default=None, max_length=160)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in REVIEW_STATUSES:
            raise ValueError("status must be pending, in_review, approved, or changes_requested")
        return value


class CommentCreate(BaseModel):
    comment: str = Field(min_length=1, max_length=5000)
    author: Optional[str] = Field(default=None, max_length=160)

    @field_validator("comment")
    @classmethod
    def comment_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("comment cannot be blank")
        return value.strip()


class RevisionCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)
    title: Optional[str] = Field(default=None, max_length=240)

    @field_validator("content")
    @classmethod
    def revision_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("revision content cannot be blank")
        return value


class CommentRead(BaseModel):
    id: int
    comment: str
    author: Optional[str]
    created_at: datetime


class RevisionRead(BaseModel):
    id: int
    content: str
    title: Optional[str]
    created_at: datetime


class ReviewRead(BaseModel):
    id: int
    title: str
    content: str
    content_type: str
    status: str
    reviewer: Optional[str]
    reviewer_name: Optional[str]
    submitted_at: datetime
    analysis_timestamp: datetime
    issue_count: int
    findings: List[FindingRead]
    comments: List[CommentRead]
    revisions: List[RevisionRead]
