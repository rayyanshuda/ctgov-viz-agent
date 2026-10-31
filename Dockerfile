# Two stages: the first builds the React app, the second is the small image that runs the server.
# Only the second stage ships, so Node and node_modules never end up in the final image.

# ---- Stage 1: build the React frontend ----
FROM node:22-slim AS frontend
WORKDIR /frontend

# Install dependencies first. Docker caches this layer, so it only re-runs when package files change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Then build. This type-checks and writes the finished site to /frontend/dist.
COPY frontend/ ./
RUN npm run build


# ---- Stage 2: the Python server ----
FROM python:3.12-slim

# uv installs the exact versions pinned in uv.lock (the same ones I develop with).
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies only, in their own layer. The app code is not installed as a package:
# it runs straight from /app (uvicorn and alembic both look in the current folder).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Put the virtualenv first on PATH so `alembic` and `uvicorn` can be called directly.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY static/ static/
# The built website goes where app/main.py looks for it: <project root>/frontend/dist
COPY --from=frontend /frontend/dist frontend/dist

# Run as a normal user instead of root. The cache folder is where the ClinicalTrials.gov
# response cache is written, and compose mounts a volume there so it survives restarts.
RUN useradd --create-home appuser && mkdir .cache && chown appuser .cache
USER appuser

EXPOSE 8000

# Docker marks the container "unhealthy" if this fails. (python is used because slim has no curl)
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"

# On every start: bring the database up to date (creates the saved_charts table the first time),
# then run the server. `exec` lets the server receive Docker's stop signal properly.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
