from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    guideline_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("brand_guidelines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    source_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    guideline = relationship("BrandGuideline")
    embeddings = relationship(
        "SourceChunkEmbedding", back_populates="source", cascade="all, delete-orphan"
    )


class SourceChunkEmbedding(Base):
    __tablename__ = "source_chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("source_id", "chunk_index", "model_name", name="uq_source_chunk_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    vector: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source = relationship("SourceDocument", back_populates="embeddings")
