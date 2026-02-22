"""Sophia Canvas - FastAPI application entry point."""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sophia_canvas.api.routes import router
from sophia_canvas.config import get_settings
from sophia_canvas.websocket.manager import manager

app = FastAPI(
    title="Sophia Canvas",
    description="Visualization and charting service for the Sophia ecosystem",
    version="0.1.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "sophia_canvas"}


@app.on_event("startup")
async def startup_event() -> None:
    """Application startup handler."""
    settings = get_settings()
    print(f"Starting Sophia Canvas on {settings.host}:{settings.port}")
    print(f"Auth enabled: {settings.auth_enabled}")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Application shutdown handler."""
    # Close all WebSocket connections gracefully
    await manager.disconnect_all()
    print("Sophia Canvas shutdown complete")


def run() -> None:
    """Run the application with uvicorn."""
    settings = get_settings()
    uvicorn.run(
        "sophia_canvas.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
