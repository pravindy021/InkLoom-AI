from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.brand_guideline import BrandGuideline
from app.schemas.guidelines import GuidelineCreate
from app.models.user import User
from app.services.auth_service import require_roles

router = APIRouter(
    prefix="/api/guidelines",
    tags=["guidelines"],
    dependencies=[Depends(require_roles("admin", "reviewer", "contributor"))],
)


def serialize_guideline(item: BrandGuideline):
    return {
        "id": item.id,
        "name": item.name,
        "category": item.category,
        "description": item.description,
        "severity": item.severity,
        "prohibited_terms": item.prohibited_terms or [],
        "preferred_terms": item.preferred_terms or [],
        "approved_sources": item.approved_sources or [],
        "status": item.status,
        "is_seed": item.is_seed,
        "created_at": item.created_at,
    }


@router.get("")
def list_guidelines(db: Session = Depends(get_db)):
    guidelines = db.query(BrandGuideline).order_by(BrandGuideline.id.asc()).all()
    return [serialize_guideline(item) for item in guidelines]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_guideline(
    payload: GuidelineCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    item = BrandGuideline(
        name=payload.name,
        category=payload.category,
        description=payload.description,
        severity=payload.severity,
        prohibited_terms=payload.prohibited_terms,
        preferred_terms=payload.preferred_terms,
        approved_sources=[source.model_dump(mode="json") for source in payload.approved_sources],
        status="approved",
        is_seed=False,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return serialize_guideline(item)


@router.delete("/{guideline_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_guideline(
    guideline_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("admin")),
):
    item = db.get(BrandGuideline, guideline_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Guideline not found.")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
