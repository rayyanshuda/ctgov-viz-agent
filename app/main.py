# Run the application with:
#   uv run uvicorn app.main:app --reload

# The ClinicalTrials.gov client is created once per process and it is shared, so the connections are pooled and the response cache is used across all requests

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.errors import register_error_handlers
from app.api.routes import router
from app.api.ratelimit import SlidingWindowLimiter
from app.cache import ResponseCache
from app.config import get_settings
from app.ctgov.client import CTGovClient

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

DEMO_DIR = Path(__file__).resolve().parent.parent / "static" / "demo"

DESCRIPTION = """\
Answers natural-language questions about clinical trials with structured visualization
specifications backed by live [ClinicalTrials.gov](https://clinicaltrials.gov/data-api/api) data.

How it works: A language model reads the question and produces a *plan* — which trials to
retrieve, how to group them, what to compute, which chart to draw. An executor then
runs that plan against the API. The model never emits a number, so every figure returned is
computed from data the API actually returned, and every data point can cite the trials behind it.

Start with: `POST /api/v1/visualize`. Use `GET /api/v1/capabilities` to discover the
dimensions, measures and chart types available, and `POST /api/v1/plan` to see how a question is
interpreted without running the retrieval.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    app.state.ctgov_client = CTGovClient(
        settings,
        ResponseCache(settings.cache_dir, settings.cache_ttl_seconds, settings.cache_enabled),
    )
    app.state.rate_limiter = SlidingWindowLimiter(
        limit=settings.rate_limit_per_hour, window_seconds=3600
    )
    if not settings.anthropic_api_key:
        # If the developer does not set an anthropic api key
        logger.warning(
            "ANTHROPIC_API_KEY is not set. /visualize and /plan will return a 503 until it is "
            "configured; see .env.example."
        )
    try:
        yield
    finally:
        await app.state.ctgov_client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ClinicalTrials.gov Query-to-Visualization Agent",
        version="1.0.0",
        description=DESCRIPTION,
        lifespan=lifespan,
    )

    # The demo page is served from the same origin, but CORS is open so the API can be
    # driven from a separately hosted frontend during development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(router, prefix="/api/v1")

    if DEMO_DIR.exists():
        app.mount("/demo", StaticFiles(directory=DEMO_DIR, html=True), name="demo")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(DEMO_DIR / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        async def index() -> JSONResponse:
            return JSONResponse({"service": "ctgov-viz-agent", "docs": "/docs"})

    return app


app = create_app()
