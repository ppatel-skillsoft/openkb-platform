# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

WORKDIR /app

# git is required to fetch openkb-core from the pinned git tag in pyproject.toml
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY alembic.ini ./

# hatch-vcs needs git history to detect version; provide a static fallback.
# openkb-core is installed from the pinned git tag in pyproject.toml.
# After install, extract the migration files from the installed package so
# alembic.ini (script_location = openkb/db/migrations) can find them.
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 pip install --no-cache-dir ".[api,db]" && \
    python -c "import shutil, os, openkb.db.migrations; \
               src = os.path.dirname(openkb.db.migrations.__file__); \
               os.makedirs('openkb/db/migrations', exist_ok=True); \
               shutil.copytree(src, 'openkb/db/migrations', dirs_exist_ok=True)"

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
