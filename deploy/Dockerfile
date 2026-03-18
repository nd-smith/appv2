FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency definition
COPY pyproject.toml .

# Install dependencies
RUN uv sync --no-dev --no-install-project

# Copy source code
COPY src/ src/
COPY config.yaml .
COPY schemas/ schemas/

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

# Copy installed venv and app code from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/config.yaml /app/config.yaml
COPY --from=builder /app/schemas /app/schemas

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# Health check port
EXPOSE 8080

# Default entrypoint — override with command in k8s manifest
ENTRYPOINT ["python", "-m"]
