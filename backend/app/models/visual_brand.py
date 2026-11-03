from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VisualBrandConfiguration(Base):
    __tablename__ = "visual_brand_configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    primary: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    secondary: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    accent: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    updated_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by = relationship("User", foreign_keys=[updated_by_id])


class VisualBrandVersion(Base):
    __tablename__ = "visual_brand_versions"
    __table_args__ = (
        UniqueConstraint(
            "version_number", name="uq_visual_brand_version_number"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    editor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    editor = relationship("User", foreign_keys=[editor_id])
