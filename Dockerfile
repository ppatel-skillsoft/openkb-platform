# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

WORKDIR /app

COPY pyproject.toml README.md ./
COPY openkb/ ./openkb/
# Also copy migration files so the migrate target can run alembic
COPY alembic.ini ./
COPY openkb/db/migrations/ ./openkb/db/migrations/

# hatch-vcs needs git history to detect version; provide a static fallback
# so the image builds from a plain file copy (no .git directory needed).
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 pip install --no-cache-dir ".[api,db]"

# Non-root user for safety
RUN useradd -m openkb

# ── api target (default) ─────────────────────────────────────────────────────
FROM base AS api
USER openkb
EXPOSE 8000
CMD ["openkb", "serve", "--host", "0.0.0.0", "--port", "8000"]

# ── migrate target ───────────────────────────────────────────────────────────
FROM base AS migrate
USER openkb
CMD ["python", "-m", "alembic", "upgrade", "head"]
