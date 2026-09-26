# ==============================================================================
# Multi-Stage Production Dockerfile for Distributed Multi-Agent Course Engine
# Security: Non-root user (UID 10001), slim runtime base, zero secret baking.
# ==============================================================================

# Stage 1: Build Dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-warn-script-location -r requirements.txt

# Stage 2: Final Distroless-style Production Runtime
FROM python:3.11-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/appuser/.local/bin:$PATH" \
    PORT=8080

# Create unprivileged application user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

# Copy installed wheels and dependencies from builder stage
COPY --from=builder /root/.local /home/appuser/.local
RUN chown -R appuser:appgroup /home/appuser/.local

# Copy application source code
COPY --chown=appuser:appgroup agents/ /app/agents/

# Security switch to non-root user
USER 10001:10001

# Cloud Run healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:' + str(__import__('os').getenv('PORT', 8080)) + '/healthz')" || exit 1

EXPOSE 8080

# Default entrypoint runs FastAPI A2A HTTP Server.
# Cloud Run injects $PORT and requires the container to listen on it.
CMD ["sh", "-c", "exec python3 -m uvicorn agents.orchestrator.a2a_server:app --host 0.0.0.0 --port ${PORT:-8080}"]
