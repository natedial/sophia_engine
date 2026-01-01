"""FastAPI application entry point for Sophia Arithmos."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings, configure_logging
from .api import router

# Configure logging before anything else
configure_logging()

logger = logging.getLogger("sophia_arithmos")

# Import computations module to trigger registration
from . import computations  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup
    from .core import registry
    logger.info("Sophia Arithmos v%s starting...", __version__)
    logger.info("Registered %d computation types", len(registry.list_all()))
    for name in sorted(registry.list_all().keys()):
        logger.debug("  - %s", name)
    yield
    # Shutdown
    logger.info("Sophia Arithmos shutting down...")


app = FastAPI(
    title="Sophia Arithmos",
    description="Computation and analysis engine for the Sophia ecosystem",
    version=__version__,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)


def run() -> None:
    """Run the application with uvicorn."""
    import uvicorn
    uvicorn.run(
        "sophia_arithmos.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
