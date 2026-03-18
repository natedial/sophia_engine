"""FastAPI entrypoint for Sophia Oikonomia."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .adapters import AdapterRegistry, BistroAdapter
from .api import build_router
from .clients import ScrivenerClient, SentryClient
from .config import settings
from .core.runtime import OikonomiaRuntime
from .core.store import OikonomiaStore

store = OikonomiaStore(Path(settings.db_path))
scrivener = ScrivenerClient(
    base_url=settings.scrivener_url,
    timeout_sec=settings.request_timeout_sec,
)
sentry = SentryClient(
    base_url=settings.sentry_url,
    timeout_sec=min(settings.request_timeout_sec, 10.0),
)
adapters = AdapterRegistry()
adapters.register(
    "bistro",
    BistroAdapter(
        scrivener=scrivener,
        market_models_root=settings.market_models_root,
        default_lookback_days=settings.default_observation_lookback_days,
    ),
)
runtime = OikonomiaRuntime(store=store, adapters=adapters, scrivener=scrivener, sentry=sentry)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    yield
    scrivener.close()
    sentry.close()


app = FastAPI(
    title="Sophia Oikonomia",
    description="Economic and market model orchestration service for the Sophia ecosystem",
    version=__version__,
    lifespan=lifespan,
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
        "sophia_oikonomia.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
