"""API routes for Sophia Canvas."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from sophia_canvas.api.schemas import (
    CanvasCreate,
    CanvasResponse,
    CanvasUpdate,
    ChartCreate,
    ChartResponse,
    ChartUpdate,
    LayoutUpdate,
    WSChartCreated,
    WSChartDeleted,
    WSChartUpdated,
    WSConnectionAck,
    WSLayoutUpdated,
)
from sophia_canvas.auth.cognito import (
    CognitoUser,
    get_current_user,
    get_optional_user,
    validate_ws_token,
)
from sophia_canvas.db.connection import get_db
from sophia_canvas.db.models import Canvas, Chart
from sophia_canvas.websocket.manager import manager

router = APIRouter()


def _verify_canvas_access(canvas: Canvas, user: CognitoUser) -> None:
    """Verify that the user has access to the canvas."""
    if canvas.user_id and canvas.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")


# ----- Canvas Endpoints -----


@router.post("/canvases", response_model=CanvasResponse, tags=["canvases"])
async def create_canvas(
    data: CanvasCreate,
    db: Session = Depends(get_db),
    user: CognitoUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new canvas for a session."""
    # Use authenticated user's ID if not explicitly provided
    user_id = data.user_id or user.user_id
    canvas = Canvas(
        session_id=data.session_id,
        user_id=user_id,
        name=data.name,
    )
    db.add(canvas)
    db.flush()
    db.refresh(canvas)
    return canvas.to_dict()


@router.get("/canvases/{canvas_id}", response_model=CanvasResponse, tags=["canvases"])
async def get_canvas(
    canvas_id: str,
    db: Session = Depends(get_db),
    user: CognitoUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a canvas by ID with all its charts."""
    try:
        canvas_uuid = uuid.UUID(canvas_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid canvas ID format")

    canvas = db.query(Canvas).filter(Canvas.id == canvas_uuid).first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")

    _verify_canvas_access(canvas, user)
    return canvas.to_dict()


@router.get("/canvases", response_model=list[CanvasResponse], tags=["canvases"])
async def list_canvases(
    session_id: str | None = Query(None, description="Filter by session ID"),
    db: Session = Depends(get_db),
    user: CognitoUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List canvases for the authenticated user, optionally filtered by session."""
    query = db.query(Canvas).filter(Canvas.user_id == user.user_id)
    if session_id:
        query = query.filter(Canvas.session_id == session_id)

    canvases = query.order_by(Canvas.updated_at.desc()).all()
    return [c.to_dict() for c in canvases]


@router.patch("/canvases/{canvas_id}", response_model=CanvasResponse, tags=["canvases"])
async def update_canvas(
    canvas_id: str,
    data: CanvasUpdate,
    db: Session = Depends(get_db),
    user: CognitoUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Update canvas metadata."""
    try:
        canvas_uuid = uuid.UUID(canvas_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid canvas ID format")

    canvas = db.query(Canvas).filter(Canvas.id == canvas_uuid).first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")

    _verify_canvas_access(canvas, user)

    if data.name is not None:
        canvas.name = data.name
    if data.layout is not None:
        canvas.layout = data.layout

    db.flush()
    db.refresh(canvas)
    return canvas.to_dict()


@router.delete("/canvases/{canvas_id}", tags=["canvases"])
async def delete_canvas(
    canvas_id: str,
    db: Session = Depends(get_db),
    user: CognitoUser = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a canvas and all its charts."""
    try:
        canvas_uuid = uuid.UUID(canvas_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid canvas ID format")

    canvas = db.query(Canvas).filter(Canvas.id == canvas_uuid).first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")

    _verify_canvas_access(canvas, user)
    db.delete(canvas)
    return {"status": "deleted", "canvas_id": canvas_id}


@router.patch("/canvases/{canvas_id}/layout", response_model=CanvasResponse, tags=["canvases"])
async def update_layout(
    canvas_id: str,
    data: LayoutUpdate,
    db: Session = Depends(get_db),
    user: CognitoUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Update chart positions in the canvas layout."""
    try:
        canvas_uuid = uuid.UUID(canvas_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid canvas ID format")

    canvas = db.query(Canvas).filter(Canvas.id == canvas_uuid).first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")

    _verify_canvas_access(canvas, user)

    # Update each chart's position
    for item in data.layout:
        try:
            chart_uuid = uuid.UUID(item.chart_id)
        except ValueError:
            continue

        chart = db.query(Chart).filter(
            Chart.id == chart_uuid,
            Chart.canvas_id == canvas_uuid,
        ).first()

        if chart:
            chart.position = {"x": item.x, "y": item.y, "w": item.w, "h": item.h}

    db.flush()
    db.refresh(canvas)

    # Broadcast layout update
    await manager.broadcast_to_canvas(
        canvas_id,
        WSLayoutUpdated(layout=[item.model_dump() for item in data.layout]).model_dump(),
    )

    return canvas.to_dict()


# ----- Chart Endpoints -----


@router.post(
    "/canvases/{canvas_id}/charts",
    response_model=ChartResponse,
    tags=["charts"],
)
async def create_chart(
    canvas_id: str,
    data: ChartCreate,
    db: Session = Depends(get_db),
    user: CognitoUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new chart in a canvas."""
    try:
        canvas_uuid = uuid.UUID(canvas_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid canvas ID format")

    canvas = db.query(Canvas).filter(Canvas.id == canvas_uuid).first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")

    _verify_canvas_access(canvas, user)

    # Calculate position if not provided
    position = data.position
    if position is None:
        # Find next available position
        existing_charts = len(canvas.charts)
        position = {"x": (existing_charts % 2) * 6, "y": (existing_charts // 2) * 4, "w": 6, "h": 4}

    chart = Chart(
        canvas_id=canvas_uuid,
        chart_type=data.chart_type,
        title=data.title,
        spec=data.spec,
        data_query=data.data_query,
        position=position,
    )
    db.add(chart)
    db.flush()
    db.refresh(chart)

    chart_dict = chart.to_dict()

    # Broadcast chart creation
    await manager.broadcast_to_canvas(
        canvas_id,
        WSChartCreated(chart=ChartResponse(**chart_dict)).model_dump(),
    )

    return chart_dict


@router.get(
    "/canvases/{canvas_id}/charts/{chart_id}",
    response_model=ChartResponse,
    tags=["charts"],
)
async def get_chart(
    canvas_id: str,
    chart_id: str,
    db: Session = Depends(get_db),
    user: CognitoUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a specific chart by ID."""
    try:
        canvas_uuid = uuid.UUID(canvas_id)
        chart_uuid = uuid.UUID(chart_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    canvas = db.query(Canvas).filter(Canvas.id == canvas_uuid).first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")

    _verify_canvas_access(canvas, user)

    chart = db.query(Chart).filter(
        Chart.id == chart_uuid,
        Chart.canvas_id == canvas_uuid,
    ).first()

    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")

    return chart.to_dict()


@router.patch(
    "/canvases/{canvas_id}/charts/{chart_id}",
    response_model=ChartResponse,
    tags=["charts"],
)
async def update_chart(
    canvas_id: str,
    chart_id: str,
    data: ChartUpdate,
    db: Session = Depends(get_db),
    user: CognitoUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Update a chart."""
    try:
        canvas_uuid = uuid.UUID(canvas_id)
        chart_uuid = uuid.UUID(chart_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    canvas = db.query(Canvas).filter(Canvas.id == canvas_uuid).first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")

    _verify_canvas_access(canvas, user)

    chart = db.query(Chart).filter(
        Chart.id == chart_uuid,
        Chart.canvas_id == canvas_uuid,
    ).first()

    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")

    updates: dict[str, Any] = {}
    if data.title is not None:
        chart.title = data.title
        updates["title"] = data.title
    if data.spec is not None:
        chart.spec = data.spec
        updates["spec"] = data.spec
    if data.data_query is not None:
        chart.data_query = data.data_query
        updates["data_query"] = data.data_query
    if data.position is not None:
        chart.position = data.position
        updates["position"] = data.position

    db.flush()
    db.refresh(chart)

    # Broadcast chart update
    if updates:
        await manager.broadcast_to_canvas(
            canvas_id,
            WSChartUpdated(chart_id=chart_id, updates=updates).model_dump(),
        )

    return chart.to_dict()


@router.delete("/canvases/{canvas_id}/charts/{chart_id}", tags=["charts"])
async def delete_chart(
    canvas_id: str,
    chart_id: str,
    db: Session = Depends(get_db),
    user: CognitoUser = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a chart from a canvas."""
    try:
        canvas_uuid = uuid.UUID(canvas_id)
        chart_uuid = uuid.UUID(chart_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    canvas = db.query(Canvas).filter(Canvas.id == canvas_uuid).first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")

    _verify_canvas_access(canvas, user)

    chart = db.query(Chart).filter(
        Chart.id == chart_uuid,
        Chart.canvas_id == canvas_uuid,
    ).first()

    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")

    db.delete(chart)

    # Broadcast chart deletion
    await manager.broadcast_to_canvas(
        canvas_id,
        WSChartDeleted(chart_id=chart_id).model_dump(),
    )

    return {"status": "deleted", "chart_id": chart_id}


# ----- WebSocket Endpoint -----


@router.websocket("/ws/{canvas_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    canvas_id: str,
    token: str | None = Query(None, description="JWT for authentication"),
) -> None:
    """WebSocket endpoint for real-time canvas updates.

    Connect to receive live updates when charts are created,
    updated, or deleted on the specified canvas.

    Pass JWT token as query param: /ws/{canvas_id}?token={jwt}
    """
    # Validate JWT token
    user = await validate_ws_token(token)
    if user is None:
        await websocket.close(code=4001, reason="Authentication required")
        return

    try:
        canvas_uuid = uuid.UUID(canvas_id)
    except ValueError:
        await websocket.close(code=4000, reason="Invalid canvas ID")
        return

    await manager.connect(websocket, canvas_id, user_id=user.user_id)

    try:
        # Send initial canvas state with user info
        await manager.send_personal(
            websocket,
            {
                "type": "connection_ack",
                "canvas_id": canvas_id,
                "user_id": user.user_id,
                "charts": [],  # Client should fetch via REST
            },
        )

        # Keep connection alive and handle incoming messages
        while True:
            try:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "ping":
                    await manager.send_personal(websocket, {"type": "pong"})
                elif msg_type == "layout_changed":
                    # Client-initiated layout change
                    # This would be handled by the REST endpoint instead
                    pass

            except Exception:
                break

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, canvas_id)
