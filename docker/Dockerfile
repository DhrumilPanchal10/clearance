# Shared image for the Python services (api, worker, payer).
# The service is selected by the `command` in docker-compose.full.yml.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    PATH="/root/.local/bin:${PATH}"

# uv for fast, reproducible installs from the committed lockfile.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the source.
COPY src ./src
COPY payer_service ./payer_service
COPY data ./data
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

# Default to the production API; overridden per service in compose.
EXPOSE 8080
CMD ["uvicorn", "clearance.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
