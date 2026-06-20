# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Install the package with the [api] extra only — keeps the image lean
COPY pyproject.toml README.md ./
COPY openkb/ ./openkb/

# hatch-vcs needs git history to detect version; provide a static fallback
# so the image builds from a plain file copy (no .git directory needed).
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 pip install --no-cache-dir ".[api]"

# Non-root user for safety
RUN useradd -m openkb
USER openkb

EXPOSE 8000

# OPENKB_STORAGE_BACKEND and other settings come from the environment /
# docker-compose.yml — no defaults baked into the image.
CMD ["openkb", "serve", "--host", "0.0.0.0", "--port", "8000"]
