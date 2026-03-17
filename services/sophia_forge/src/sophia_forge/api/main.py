"""FastAPI entrypoint for the forge service."""

from __future__ import annotations

from fastapi import FastAPI

from sophia_forge.backends import build_backend_executor
from sophia_forge.config import ForgeSettings
from sophia_forge.core.runtime import ForgeRuntime
from sophia_forge.api.routes import build_router


def create_app(
    *,
    runtime: ForgeRuntime | None = None,
    settings: ForgeSettings | None = None,
) -> FastAPI:
    app = FastAPI(title="Sophia Forge", version="0.1.0")
    resolved_settings = settings or ForgeSettings()
    app.state.runtime = runtime or ForgeRuntime(
        settings=resolved_settings,
        executor=build_backend_executor(settings=resolved_settings),
    )
    app.include_router(build_router(app.state.runtime))

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    return app
