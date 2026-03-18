"""FastAPI entrypoint for Sophia Sentry."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import build_router
from .config import settings
from .core.runtime import SentryRuntime
from .core.store import SentryStore

store = SentryStore(Path(settings.db_path))
runtime = SentryRuntime(store=store)

app = FastAPI(
    title="Sophia Sentry",
    description="Background watch and alert runtime for the Sophia ecosystem",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(build_router(runtime))


def run() -> None:
    """Run the application with uvicorn."""
    import uvicorn

    uvicorn.run(
        "sophia_sentry.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
