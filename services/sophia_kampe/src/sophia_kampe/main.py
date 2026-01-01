"""FastAPI application entry point for Sophia Kampe."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings
from .api import router
from .clients.arithmos import arithmos_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup
    print(f"Sophia Kampe v{__version__} starting...")
    print(f"Arithmos endpoint: {settings.arithmos.url}")
    await arithmos_client.start()
    yield
    # Shutdown
    await arithmos_client.stop()
    print("Sophia Kampe shutting down...")


app = FastAPI(
    title="Sophia Kampe",
    description="Yield curve management service for the Sophia ecosystem",
    version=__version__,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        "sophia_kampe.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
