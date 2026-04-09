# Multi-stage build for Python Poetry applications
# Usage: docker build --build-arg PYTHON_VERSION=3.12 ...
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm AS base

ARG BUILD_ENV=dev
ARG POETRY_VERSION=2.1.1
ARG POETRY_INSTALL_ARGS="--no-interaction --no-ansi"
ARG POETRY_INSTALLER_MAX_WORKERS=4
ARG PORT=8000
ARG PYTHON_VERSION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

# curl: healthchecks; git: private VCS deps; build-essential: some wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /app

# ---------------------------------------------------------------------------
# Install dependencies only (layer cache friendly)
# ---------------------------------------------------------------------------
FROM base AS deps

# Root project metadata first
COPY pyproject.toml poetry.lock* ./

# Optional: monorepo / local path deps — copy declared packages if you use [tool.poetry.packages] or path deps.
# Uncomment and adjust if your repo has multiple installable roots:
# COPY packages ./packages

# GitHub token for private Git deps or index (mirrors Maven settings.xml pattern)
RUN --mount=type=secret,id=git_token \
    if [ -f /run/secrets/git_token ]; then \
      GIT_TOKEN=$(cat /run/secrets/git_token) && \
      git config --global url."https://github:${GIT_TOKEN}@github.com/".insteadOf "https://github.com/"; \
    fi

RUN --mount=type=secret,id=git_token \
    poetry install ${POETRY_INSTALL_ARGS} --only main --no-root || true

# Warm lock resolution / wheels when lock exists
RUN --mount=type=secret,id=git_token \
    if [ -f poetry.lock ]; then \
      poetry install ${POETRY_INSTALL_ARGS} --only main --no-root; \
    else \
      echo "No poetry.lock — resolve deps from pyproject.toml" && \
      poetry lock && poetry install ${POETRY_INSTALL_ARGS} --only main --no-root; \
    fi

RUN rm -rf "${POETRY_CACHE_DIR}"

# ---------------------------------------------------------------------------
# Build / install application
# ---------------------------------------------------------------------------
FROM base AS builder

COPY --from=deps /app /app

# Full source (same idea as Java: copy all, then use what you need)
COPY . /build-context/

# Single-package layout: use repo root as project root
# If your app lives in a subdir (e.g. services/api), replace the RUN block with:
#   RUN cp -r /build-context/services/api/. /app/ && rm -rf /build-context
RUN \
  if [ ! -f /build-context/pyproject.toml ]; then \
    echo "Error: pyproject.toml not found in build context" && exit 1; \
  fi && \
  cp -f /build-context/pyproject.toml /app/ && \
  if [ -f /build-context/poetry.lock ]; then cp -f /build-context/poetry.lock /app/; fi && \
  rsync -a --delete \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.venv' \
    /build-context/ /app/ && \
  rm -rf /build-context

RUN --mount=type=secret,id=git_token \
    if [ -f /run/secrets/git_token ]; then \
      GIT_TOKEN=$(cat /run/secrets/git_token) && \
      git config --global url."https://github:${GIT_TOKEN}@github.com/".insteadOf "https://github.com/"; \
    fi

RUN --mount=type=secret,id=git_token \
    echo "Building for environment: ${BUILD_ENV}" && \
    poetry install ${POETRY_INSTALL_ARGS} --only main && \
    echo "Installed packages:" && poetry show --tree || true

# ---------------------------------------------------------------------------
# Production image — copy venv only, run module or script
# ---------------------------------------------------------------------------
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm AS runner

ARG PORT=8000
ARG PYTHON_VERSION
ARG POETRY_APP_MODULE=""
# If empty, ENTRYPOINT uses POETRY_SCRIPT below
ARG POETRY_SCRIPT=""

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/app/.venv/bin:${PATH}" \
    PORT=${PORT}

RUN groupadd --system --gid 1001 appuser && \
    useradd --system --uid 1001 --gid appuser appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app /app

# Drop dev-only / cache junk if any landed in /app
RUN rm -rf /app/.venv/poetry_cache 2>/dev/null || true

USER appuser

EXPOSE ${PORT}

# Prefer module (e.g. myservice.main:app for uvicorn) or a console script from pyproject [tool.poetry.scripts]
RUN echo '#!/bin/sh' > /app/entrypoint.sh && \
    echo 'set -e' >> /app/entrypoint.sh && \
    echo 'if [ -n "${POETRY_APP_MODULE}" ]; then' >> /app/entrypoint.sh && \
    echo '  exec python -m "${POETRY_APP_MODULE}" "$@"' >> /app/entrypoint.sh && \
    echo 'elif [ -n "${POETRY_SCRIPT}" ]; then' >> /app/entrypoint.sh && \
    echo "  exec \"${POETRY_SCRIPT}\" \"\$@\"" >> /app/entrypoint.sh && \
    echo 'else' >> /app/entrypoint.sh && \
    echo '  echo "Set POETRY_APP_MODULE (e.g. uvicorn myapp.main:app) or POETRY_SCRIPT at build time"' >> /app/entrypoint.sh && \
    echo '  exit 1' >> /app/entrypoint.sh && \
    echo 'fi' >> /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

# Bake defaults at build time (override with --build-arg)
ARG POETRY_APP_MODULE
ARG POETRY_SCRIPT
ENV POETRY_APP_MODULE=${POETRY_APP_MODULE} \
    POETRY_SCRIPT=${POETRY_SCRIPT}

ENTRYPOINT ["/app/entrypoint.sh"]