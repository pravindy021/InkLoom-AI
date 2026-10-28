from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.config import MAX_SOURCE_UPLOAD_SIZE
from app.database import get_db
from app.models.brand_guideline import BrandGuideline
from app.models.source_document import SourceApprovalEvent, SourceDocument
from app.schemas.sources import SourceApprovalUpdate, SourceCreate, SourceRead
from app.services.document_ingestion import extract_source_text
from app.models.user import User
from app.services.auth_service import require_roles

router = APIRouter(
    prefix="/api/sources",
    tags=["evidence sources"],
    dependencies=[Depends(require_roles("admin", "reviewer", "contributor"))],
)


def _serialize(source: SourceDocument):
    return {
        "id": source.id,
        "name": source.name,
        "content": source.content,
        "guideline_id": source.guideline_id,
        "url": source.url,
        "source_date": source.source_date,
        "expiry_date": source.expiry_date,
        "approval_status": source.approval_status,
        "reviewed_by_id": source.reviewed_by_id,
        "reviewed_by": source.reviewed_by.display_name if source.reviewed_by else None,
        "reviewed_at": source.reviewed_at,
        "review_note": source.review_note,
        "approval_history": [
            {
                "status": event.status,
                "reviewer": event.reviewer.display_name if event.reviewer else None,
                "note": event.note,
                "created_at": event.created_at,
            }
            for event in source.approval_history
        ],
        "created_at": source.created_at,
    }


@router.get("", response_model=list[SourceRead])
def list_sources(
    guideline_id: int = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    query = db.query(SourceDocument)
    if guideline_id is not None:
        query = query.filter(SourceDocument.guideline_id == guideline_id)
    return [_serialize(source) for source in query.order_by(SourceDocument.id.desc()).all()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SourceRead)
def create_source(
    payload: SourceCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    if payload.guideline_id is not None and db.get(BrandGuideline, payload.guideline_id) is None:
        raise HTTPException(status_code=422, detail="The selected guideline does not exist.")
    source = SourceDocument(**payload.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return _serialize(source)


@router.post("/upload", status_code=status.HTTP_201_CREATED, response_model=SourceRead)
async def upload_source(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    guideline_id: int = Form(default=None),
    url: str = Form(default=""),
    source_date: date = Form(default=None),
    expiry_date: date = Form(default=None),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    filename = (file.filename or "").replace("\\", "/").split("/")[-1].strip()
    if not filename or any(ord(char) < 32 for char in filename):
        raise HTTPException(status_code=422, detail="A valid source filename is required.")
    if guideline_id is not None and db.get(BrandGuideline, guideline_id) is None:
        raise HTTPException(status_code=422, detail="The selected guideline does not exist.")
    if source_date and expiry_date and expiry_date < source_date:
        raise HTTPException(status_code=422, detail="expiry_date cannot precede source_date.")
    file_bytes = await file.read(MAX_SOURCE_UPLOAD_SIZE + 1)
    if len(file_bytes) > MAX_SOURCE_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Source file exceeds the configured size limit.")
    try:
        content = extract_source_text(filename, file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    source = SourceDocument(
        name=(name or "").strip()[:160] or filename[:160],
        content=content,
        guideline_id=guideline_id,
        url=(url or "").strip() or None,
        source_date=source_date,
        expiry_date=expiry_date,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return _serialize(source)


@router.patch("/{source_id}/approval", response_model=SourceRead)
def update_source_approval(
    source_id: int,
    payload: SourceApprovalUpdate,
    db: Session = Depends(get_db),
    reviewer: User = Depends(require_roles("admin", "reviewer")),
):
    source = db.get(SourceDocument, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Evidence source not found.")
    source.approval_status = payload.status
    source.reviewed_by_id = reviewer.id
    source.reviewed_at = datetime.now(timezone.utc)
    source.review_note = payload.note
    db.add(
        SourceApprovalEvent(
            source=source,
            reviewer_id=reviewer.id,
            status=payload.status,
            note=payload.note,
        )
    )
    db.commit()
    db.refresh(source)
    return _serialize(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    source = db.get(SourceDocument, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Approved source not found.")
    db.delete(source)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
