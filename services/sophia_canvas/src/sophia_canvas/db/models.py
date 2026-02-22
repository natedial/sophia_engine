"""SQLAlchemy ORM models for Sophia Canvas."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Canvas(Base):
    """Dashboard canvas containing multiple charts.

    A canvas represents a single dashboard view that can contain
    multiple chart visualizations arranged in a grid layout.
    """

    __tablename__ = "canvases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), default="Untitled Dashboard")
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    charts: Mapped[list["Chart"]] = relationship(
        back_populates="canvas", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "session_id": self.session_id,
            "user_id": self.user_id,
            "name": self.name,
            "layout": self.layout,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "charts": [chart.to_dict() for chart in self.charts],
        }


class Chart(Base):
    """Individual chart visualization within a canvas.

    Charts store their Vega-Lite specification and position
    within the parent canvas grid layout.
    """

    __tablename__ = "charts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    canvas_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canvases.id", ondelete="CASCADE")
    )
    chart_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    data_query: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    position: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=lambda: {"x": 0, "y": 0, "w": 6, "h": 4}
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    canvas: Mapped["Canvas"] = relationship(back_populates="charts")

    __table_args__ = (Index("idx_charts_canvas", "canvas_id"),)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "canvas_id": str(self.canvas_id),
            "chart_type": self.chart_type,
            "title": self.title,
            "spec": self.spec,
            "data_query": self.data_query,
            "position": self.position,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
