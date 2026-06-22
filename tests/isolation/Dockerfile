FROM python:3.12-slim

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv==0.5.18

# git is required to fetch openkb-core from the pinned git tag in pyproject.toml
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files needed to install the isolation-tests extra
COPY pyproject.toml README.md ./
# Minimal stubs for compiler_worker and generator_api so uv can resolve the package.
# openkb-core is pulled as a pip dep (no local openkb/ source needed).
RUN mkdir -p compiler_worker generator_api \
    && touch compiler_worker/__init__.py generator_api/__init__.py

# SETUPTOOLS_SCM_PRETEND_VERSION is required because .git is excluded from the build context.
# openkb-core is pulled from the pinned git tag in pyproject.toml.
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 uv pip install --system --no-cache ".[isolation-tests]"

# Copy the isolation test sources
COPY tests/isolation/ ./tests/isolation/

# Default: run all isolation tests
ENTRYPOINT ["python", "-m", "pytest", "tests/isolation/", "-v", "--tb=short"]
