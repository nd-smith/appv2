FROM python:3.12-slim AS builder

WORKDIR /app

# Copy dependency definition
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ src/
COPY config.yaml .
COPY schemas/ schemas/

# --- Runtime stage ---
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages and app code from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/src /app/src
COPY --from=builder /app/config.yaml /app/config.yaml
COPY --from=builder /app/schemas /app/schemas

ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1

# Health check port
EXPOSE 8080

# Default entrypoint — override with command in k8s manifest
ENTRYPOINT ["python", "-m"]
