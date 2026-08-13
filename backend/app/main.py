"""Chakravyuh API entrypoint.

Run with:  uvicorn app.main:app --reload --port 8000   (from `backend/`)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.config import settings

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    logging.getLogger(__name__).info(
        "chakravyuh v%s (phase %d) ready on %s:%d",
        settings.version,
        settings.phase,
        settings.host,
        settings.port,
    )
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

# Routers added as each phase lands:
#   phase 1-2: scenarios, graph
#   phase 4:   interdict
#   phase 5:   ws_replay
#   phase 6:   evaluate
