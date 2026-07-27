"""API routes for Sophia Arithmos."""

import logging
import time

from fastapi import APIRouter, HTTPException

from .. import __version__
from ..config import settings
from ..core import registry, get_computation, Observation, OutputMode
from .schemas import (
    ComputeRequest,
    ComputeResponse,
    ComputationResultOutput,
    ComputationTypesResponse,
    ComputationTypeInfo,
    HealthResponse,
    ObservationOutput,
)

logger = logging.getLogger("sophia_arithmos.api")

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        service="sophia_arithmos",
        version=__version__,
        computations_available=len(registry.list_all()),
    )


@router.get("/compute/types", response_model=ComputationTypesResponse)
async def list_computation_types() -> ComputationTypesResponse:
    """List all available computation types with their schemas."""
    schemas = registry.list_schemas()

    types = {
        name: ComputationTypeInfo(
            name=schema["name"],
            description=schema["description"],
            params=schema["params"],
            precision_type=schema["precision_type"],
        )
        for name, schema in schemas.items()
    }

    return ComputationTypesResponse(types=types, count=len(types))


@router.post("/compute", response_model=ComputeResponse)
async def compute(request: ComputeRequest) -> ComputeResponse:
    """Execute one or more computations on the provided data."""
    request_start = time.perf_counter()
    logger.info(
        "POST /compute | data_points=%d | computation_count=%d",
        len(request.data),
        len(request.computations),
    )

    # Validate request limits
    if len(request.data) > settings.max_input_points:
        logger.warning(
            "Request rejected: too many data points (%d > %d)",
            len(request.data),
            settings.max_input_points,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Too many data points: {len(request.data)} exceeds limit of {settings.max_input_points}",
        )

    if len(request.computations) > settings.max_computations:
        logger.warning(
            "Request rejected: too many computations (%d > %d)",
            len(request.computations),
            settings.max_computations,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Too many computations: {len(request.computations)} exceeds limit of {settings.max_computations}",
        )

    # Convert input data to internal format
    data = [
        Observation(date=obs.date, value=obs.value)
        for obs in request.data
    ]

    # Sort by date to ensure chronological order
    data.sort(key=lambda x: x.date)

    # Determine output mode
    output_mode = OutputMode(request.output)

    # Execute each computation
    results: dict[str, ComputationResultOutput] = {}

    for comp_req in request.computations:
        result_key = comp_req.id or comp_req.type

        # Get the computation
        computation = get_computation(comp_req.type)
        if computation is None:
            logger.error(
                "Unknown computation type requested: %s",
                comp_req.type,
            )
            results[result_key] = ComputationResultOutput(
                error=f"Unknown computation type: {comp_req.type}",
                metadata={"requested_type": comp_req.type},
            )
            continue

        # Execute computation
        try:
            result = computation.execute(data, comp_req.params, output_mode)

            # Convert to output format
            results[result_key] = ComputationResultOutput(
                series=[
                    ObservationOutput(date=obs.date, value=obs.value)
                    for obs in result.series
                ] if result.series else None,
                latest=ObservationOutput(
                    date=result.latest.date,
                    value=result.latest.value,
                ) if result.latest else None,
                summary=result.summary,
                metadata=result.metadata,
            )

        except ValueError as e:
            logger.warning(
                "Computation '%s' validation error: %s",
                comp_req.type,
                str(e),
            )
            results[result_key] = ComputationResultOutput(
                error=str(e),
                metadata={"computation": comp_req.type},
            )
        except Exception as e:
            logger.exception(
                "Computation '%s' failed with unexpected error",
                comp_req.type,
            )
            results[result_key] = ComputationResultOutput(
                error=f"Computation failed: {str(e)}",
                metadata={"computation": comp_req.type},
            )

    # Build response metadata
    succeeded = sum(1 for r in results.values() if r.error is None)
    failed = len(results) - succeeded

    elapsed_ms = (time.perf_counter() - request_start) * 1000
    logger.info(
        "POST /compute complete | succeeded=%d | failed=%d | elapsed=%.2fms",
        succeeded,
        failed,
        elapsed_ms,
    )

    return ComputeResponse(
        results=results,
        metadata={
            "input_points": len(data),
            "date_range": {
                "start": data[0].date.isoformat(),
                "end": data[-1].date.isoformat(),
            },
            "computations_requested": len(request.computations),
            "computations_succeeded": succeeded,
            "computations_failed": failed,
        },
    )
