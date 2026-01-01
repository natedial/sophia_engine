"""API routes for Sophia Kampe."""

from fastapi import APIRouter, HTTPException

from .. import __version__
from ..clients import arithmos_client
from ..core import model_store

# Legacy alias
curve_store = model_store
from .schemas import (
    CurveListResponse,
    CurveResponse,
    FitCurveRequest,
    HealthResponse,
    InterpolateRequest,
    InterpolateResponse,
    RefineCurveRequest,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    # Check Arithmos connectivity
    arithmos_status = None
    try:
        health = await arithmos_client.health()
        arithmos_status = health.get("status", "unknown")
    except Exception:
        arithmos_status = "unreachable"

    stats = curve_store.stats()

    return HealthResponse(
        status="healthy",
        service="sophia_kampe",
        version=__version__,
        arithmos_status=arithmos_status,
        curves_count=stats["total_models"],  # total models, not just curves
    )


@router.get("/curves", response_model=CurveListResponse)
async def list_curves() -> CurveListResponse:
    """List all curves."""
    curves = curve_store.list_all()
    return CurveListResponse(
        curves=[
            CurveResponse(
                id=c.id,
                name=c.name,
                curve_type=c.curve_type,
                state=c.state,
                as_of_date=c.as_of_date,
                fitted_at=c.fitted_at,
                published_at=c.published_at,
                parameters=c.parameters,
                constraints=c.constraints,
                metadata=c.metadata,
            )
            for c in curves
        ],
        count=len(curves),
    )


@router.get("/curves/{curve_id}", response_model=CurveResponse)
async def get_curve(curve_id: str) -> CurveResponse:
    """Get a specific curve by ID."""
    curve = curve_store.get(curve_id)
    if not curve:
        raise HTTPException(status_code=404, detail=f"Curve not found: {curve_id}")

    return CurveResponse(
        id=curve.id,
        name=curve.name,
        curve_type=curve.curve_type,
        state=curve.state,
        as_of_date=curve.as_of_date,
        fitted_at=curve.fitted_at,
        published_at=curve.published_at,
        parameters=curve.parameters,
        constraints=curve.constraints,
        metadata=curve.metadata,
    )


@router.post("/curves", response_model=CurveResponse, status_code=201)
async def fit_curve(request: FitCurveRequest) -> CurveResponse:
    """Fit a new yield curve.

    This endpoint:
    1. Validates input data
    2. Calls Arithmos for the actual fitting
    3. Stores the resulting curve
    4. Optionally publishes it
    """
    # TODO: Implement curve fitting workflow
    # 1. Generate curve ID
    # 2. Create Curve object in PENDING state
    # 3. Call arithmos_client to fit
    # 4. Update curve with parameters
    # 5. Apply constraints if any
    # 6. Update state to FITTED or PUBLISHED

    raise HTTPException(
        status_code=501,
        detail="Curve fitting not yet implemented. This is a scaffold.",
    )


@router.post("/curves/{curve_id}/refine", response_model=CurveResponse)
async def refine_curve(curve_id: str, request: RefineCurveRequest) -> CurveResponse:
    """Refine an existing curve with updated constraints."""
    curve = curve_store.get(curve_id)
    if not curve:
        raise HTTPException(status_code=404, detail=f"Curve not found: {curve_id}")

    # TODO: Implement refinement workflow
    # 1. Update constraints
    # 2. Re-fit with constraints via Arithmos
    # 3. Update curve parameters
    # 4. Optionally publish

    raise HTTPException(
        status_code=501,
        detail="Curve refinement not yet implemented. This is a scaffold.",
    )


@router.post("/curves/{curve_id}/publish", response_model=CurveResponse)
async def publish_curve(curve_id: str) -> CurveResponse:
    """Publish a fitted curve, making it available for consumption."""
    curve = curve_store.get(curve_id)
    if not curve:
        raise HTTPException(status_code=404, detail=f"Curve not found: {curve_id}")

    # TODO: Implement publish workflow
    # 1. Validate curve is in FITTED state
    # 2. Update state to PUBLISHED
    # 3. Set published_at timestamp

    raise HTTPException(
        status_code=501,
        detail="Curve publishing not yet implemented. This is a scaffold.",
    )


@router.post("/curves/interpolate", response_model=InterpolateResponse)
async def interpolate(request: InterpolateRequest) -> InterpolateResponse:
    """Interpolate yields from a published curve."""
    curve = curve_store.get(request.curve_id)
    if not curve:
        raise HTTPException(status_code=404, detail=f"Curve not found: {request.curve_id}")

    # TODO: Implement interpolation
    # 1. Get curve parameters
    # 2. Calculate yields at requested maturities
    # 3. Return results

    raise HTTPException(
        status_code=501,
        detail="Interpolation not yet implemented. This is a scaffold.",
    )


@router.delete("/curves/{curve_id}", status_code=204)
async def delete_curve(curve_id: str) -> None:
    """Delete a curve."""
    if not curve_store.delete(curve_id):
        raise HTTPException(status_code=404, detail=f"Curve not found: {curve_id}")
