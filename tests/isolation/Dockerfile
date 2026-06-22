FROM python:3.12-slim

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv==0.5.18

WORKDIR /app

# Copy project files needed to install the isolation-tests extra
COPY pyproject.toml README.md ./
# Minimal stub so uv can resolve the package without building everything
RUN mkdir -p openkb compiler_worker generator_api \
    && touch openkb/__init__.py compiler_worker/__init__.py generator_api/__init__.py

# SETUPTOOLS_SCM_PRETEND_VERSION is required because .git is excluded from the
# build context — hatch-vcs uses setuptools-scm and needs a fallback version.
RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 uv pip install --system --no-cache ".[isolation-tests]"

# Copy the isolation test sources
COPY tests/isolation/ ./tests/isolation/

# Default: run all isolation tests
ENTRYPOINT ["python", "-m", "pytest", "tests/isolation/", "-v", "--tb=short"]
