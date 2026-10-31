# Run the application with:
#   uv run uvicorn app.main:app --reload

# The ClinicalTrials.gov client is created once per process and it is shared, so the connections are pooled and the response cache is used across all requests

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.charts import router as charts_router
from app.api.errors import register_error_handlers
from app.api.routes import router
from app.api.ratelimit import SlidingWindowLimiter
from app.cache import ResponseCache
from app.config import get_settings
from app.ctgov.client import CTGovClient
from app.db.engine import make_engine, make_session_factory

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT_DIR / "static" / "demo"  # the original single-file demo page
FRONTEND_DIR = ROOT_DIR / "frontend" / "dist"  # the React app, created by `npm run build`

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
    # loads data like the folders, limits, and secrets (env var)
    app.state.ctgov_client = CTGovClient(
        settings,
        ResponseCache(settings.cache_dir, settings.cache_ttl_seconds, settings.cache_enabled),
    )
    app.state.rate_limiter = SlidingWindowLimiter(
        limit=settings.rate_limit_per_hour, window_seconds=3600
    )
    # The database is optional. app.state.db is the session factory, or None when saving is off.
    engine = make_engine(settings.database_url) if settings.database_url else None
    app.state.db = make_session_factory(engine) if engine else None
    if not settings.anthropic_api_key:
        # If the developer does not set an anthropic api key
        logger.warning(
            "ANTHROPIC_API_KEY is not set. /visualize and /plan will return a 503 until it is "
            "configured; see .env.example."
        )
    try:
        yield
    finally:
        # close connection to external database
        await app.state.ctgov_client.aclose()
        if engine:
            await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ClinicalTrials.gov Query-to-Visualization Agent",
        version="1.0.0",
        description=DESCRIPTION,
        lifespan=lifespan,
    )

    # The demo page is served from the same origin, but CORS is open so the API can be
    # driven from a separately hosted frontend during development.
    # * just means any url can send a request to the fastapi backend (not very secure if a future implementation is logins or contains user data)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.include_router(charts_router, prefix="/api/v1")

    if DEMO_DIR.exists():
        app.mount("/demo", StaticFiles(directory=DEMO_DIR, html=True), name="demo")

    if (FRONTEND_DIR / "index.html").exists():
        # The React app. Vite puts its JS and CSS files in dist/assets.
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

        @app.get("/legacy", include_in_schema=False)
        async def legacy() -> FileResponse:
            return FileResponse(DEMO_DIR / "index.html")

        # Pages like /charts and /c/abc123 only exist inside the React app (its router draws
        # them), so for any other URL we return index.html and let React take over. This must
        # be registered last: FastAPI's own routes (/docs, /api/v1/...) are matched first.
        @app.get("/{path:path}", include_in_schema=False)
        async def react_app(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(status_code=404)  # a mistyped API URL should not return a web page
            return FileResponse(FRONTEND_DIR / "index.html")

    elif DEMO_DIR.exists():

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(DEMO_DIR / "index.html")

    else:

        @app.get("/", include_in_schema=False)
        async def index() -> JSONResponse:
            return JSONResponse({"service": "ctgov-viz-agent", "docs": "/docs"})

    return app


app = create_app()
