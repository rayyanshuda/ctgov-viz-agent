# Map the domain exceptions to HTTP responses
# A remedy tells the caller what to do, so it knows what went wrong, and how to move forward

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.ratelimit import RateLimitedError
from app.errors import (
    AnalysisError,
    ConfigurationError,
    CtgovVizError,
    PlanningError,
    UnsupportedQueryError,
    UpstreamError,
)
from app.models.response import ErrorResponse

logger = logging.getLogger(__name__)

STATUS_BY_ERROR: dict[type[CtgovVizError], int] = {
    ConfigurationError: 503,
    UpstreamError: 502,
    PlanningError: 422,
    UnsupportedQueryError: 422,
    AnalysisError: 500,
    RateLimitedError: 429,
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(CtgovVizError)
    async def _handle_domain_error(_: Request, exc: CtgovVizError) -> JSONResponse:
        status = STATUS_BY_ERROR.get(type(exc), 500)
        if status >= 500:
            logger.error("%s: %s", type(exc).__name__, exc.message, exc_info=True)
        else:
            logger.info("%s: %s", type(exc).__name__, exc.message)
        return JSONResponse(
            status_code=status,
            content=ErrorResponse(
                error=exc.code, message=exc.message, remedy=exc.remedy
            ).model_dump(exclude_none=True),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error")
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="internal_error",
                message=f"An unexpected error occurred: {type(exc).__name__}.",
            ).model_dump(exclude_none=True),
        )
