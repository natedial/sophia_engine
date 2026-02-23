"""FastAPI application for sophia_tholos research search service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from sophia_tholos.api.routes import router
from sophia_tholos.config import Settings
from sophia_tholos.core.corpus import init_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    logger.info(
        "sophia_tholos starting — db=%s  npz=%s  model=%s",
        settings.db_path,
        settings.npz_path,
        settings.model_name,
    )
    init_engine(
        db_path=settings.db_path,
        npz_path=settings.npz_path,
        model_name=settings.model_name,
    )
    yield


app = FastAPI(title="sophia_tholos", version="0.1.0", lifespan=lifespan)
app.include_router(router)


if __name__ == "__main__":
    settings = Settings()
    uvicorn.run(
        "sophia_tholos.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
