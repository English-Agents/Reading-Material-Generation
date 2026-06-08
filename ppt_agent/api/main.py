"""
FastAPI application factory.

Lifespan:
  - startup: open Redis pool, launch ops background job
  - shutdown: close Redis pool, cancel background job
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ppt_agent.config.settings import settings

logger = logging.getLogger(__name__)

_ops_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ──────────────────────────────────────────────────────────────
    app.state.redis = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )
    logger.info("Redis pool opened: %s", settings.redis_url)

    global _ops_task
    from ppt_agent.api.ops import ops_background_job
    _ops_task = asyncio.create_task(ops_background_job())
    logger.info("Ops background job started")

    yield

    # ── shutdown ──────────────────────────────────────────────────────────────
    if _ops_task and not _ops_task.done():
        _ops_task.cancel()
        try:
            await _ops_task
        except asyncio.CancelledError:
            pass

    await app.state.redis.aclose()
    logger.info("Redis pool closed")


def create_app() -> FastAPI:
    app = FastAPI(
        title="RMG — Reading Material Generator",
        version="0.1.0",
        lifespan=lifespan,
    )

    origins = settings.cors_origins_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from ppt_agent.api.export import router as export_router
    from ppt_agent.api.generate import router as generate_router
    from ppt_agent.api.ops import router as ops_router
    from ppt_agent.api.review import router as review_router

    app.include_router(generate_router, prefix="/generate", tags=["generate"])
    app.include_router(review_router, prefix="/review", tags=["review"])
    app.include_router(ops_router, prefix="/ops", tags=["ops"])
    app.include_router(export_router, prefix="/export", tags=["export"])

    @app.get("/healthz", tags=["health"])
    async def healthz():
        return {"status": "ok"}

    return app


app = create_app()
