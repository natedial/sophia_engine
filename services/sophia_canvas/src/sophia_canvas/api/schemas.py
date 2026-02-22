"""Pydantic schemas for API requests and responses."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ----- Canvas Schemas -----


class CanvasCreate(BaseModel):
    """Request to create a new canvas."""

    session_id: str = Field(..., description="Agent session ID")
    user_id: str | None = Field(None, description="User ID (from auth)")
    name: str = Field(default="Untitled Dashboard", description="Canvas name")


class CanvasUpdate(BaseModel):
    """Request to update canvas metadata."""

    name: str | None = Field(None, description="New canvas name")
    layout: dict[str, Any] | None = Field(None, description="Grid layout metadata")


class LayoutItem(BaseModel):
    """Position of a chart in the grid layout."""

    chart_id: str = Field(..., description="Chart ID")
    x: int = Field(..., ge=0, description="Grid column position")
    y: int = Field(..., ge=0, description="Grid row position")
    w: int = Field(..., ge=1, description="Width in grid units")
    h: int = Field(..., ge=1, description="Height in grid units")


class LayoutUpdate(BaseModel):
    """Request to update canvas layout."""

    layout: list[LayoutItem] = Field(..., description="Chart positions")


class ChartResponse(BaseModel):
    """Chart in API response."""

    id: str
    canvas_id: str
    chart_type: str
    title: str | None
    spec: dict[str, Any]
    data_query: dict[str, Any] | None
    position: dict[str, Any]
    created_at: str | None
    updated_at: str | None


class CanvasResponse(BaseModel):
    """Canvas in API response."""

    id: str
    session_id: str
    user_id: str | None
    name: str
    layout: dict[str, Any]
    created_at: str | None
    updated_at: str | None
    charts: list[ChartResponse]


# ----- Chart Schemas -----


class ChartCreate(BaseModel):
    """Request to create a new chart."""

    chart_type: str = Field(..., description="Type of chart (timeseries, bar, scatter, etc.)")
    title: str | None = Field(None, description="Chart title")
    spec: dict[str, Any] = Field(..., description="Vega-Lite specification")
    data_query: dict[str, Any] | None = Field(
        None, description="Query to fetch/refresh data"
    )
    position: dict[str, Any] | None = Field(
        None, description="Grid position {x, y, w, h}"
    )


class ChartUpdate(BaseModel):
    """Request to update a chart."""

    title: str | None = Field(None, description="New chart title")
    spec: dict[str, Any] | None = Field(None, description="Updated Vega-Lite spec")
    data_query: dict[str, Any] | None = Field(None, description="Updated data query")
    position: dict[str, Any] | None = Field(None, description="Updated position")


# ----- WebSocket Message Schemas -----


class WSMessage(BaseModel):
    """Base WebSocket message."""

    type: str


class WSChartCreated(WSMessage):
    """Sent when a chart is created."""

    type: str = "chart_created"
    chart: ChartResponse


class WSChartUpdated(WSMessage):
    """Sent when a chart is updated."""

    type: str = "chart_updated"
    chart_id: str
    updates: dict[str, Any]


class WSChartDeleted(WSMessage):
    """Sent when a chart is deleted."""

    type: str = "chart_deleted"
    chart_id: str


class WSLayoutUpdated(WSMessage):
    """Sent when layout is updated."""

    type: str = "layout_updated"
    layout: list[dict[str, Any]]


class WSConnectionAck(WSMessage):
    """Sent on successful WebSocket connection."""

    type: str = "connection_ack"
    canvas_id: str
    charts: list[ChartResponse]


class WSError(WSMessage):
    """Sent on error."""

    type: str = "error"
    message: str
    code: str | None = None
