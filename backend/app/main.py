"""Chakravyuh API entrypoint.

Run with:  uvicorn app.main:app --reload --port 8000   (from `backend/`)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    account,
    evaluate,
    graph,
    health,
    interdict,
    scenarios,
    session,
    ws_replay,
)
from app.config import settings

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(__name__)
    log.info(
        "chakravyuh v%s (phase %d) ready on %s:%d",
        settings.version,
        settings.phase,
        settings.host,
        settings.port,
    )

    # Build the stage scenario's context off the request path. Tracing,
    # featurising and rolling out an incident takes a couple of seconds, and
    # the first click of a demo is not the moment to spend them.
    await asyncio.to_thread(session.warm, "S1")
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Chakravyuh",
    description=(
        "Real-time financial fraud interdiction. Given a fraud complaint, "
        "computes which accounts to freeze, in what order, to maximise "
        "rupees recovered under a hard budget on innocent freezes."
    ),
    version=settings.version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(scenarios.router, prefix="/api", tags=["scenarios"])
app.include_router(graph.router, prefix="/api", tags=["graph"])
app.include_router(interdict.router, prefix="/api", tags=["interdict"])
app.include_router(account.router, prefix="/api", tags=["inspect"])
app.include_router(evaluate.router, prefix="/api", tags=["evaluate"])
app.include_router(ws_replay.router, tags=["replay"])
