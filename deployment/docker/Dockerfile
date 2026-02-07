# ARISP Pipeline Docker Image
# Multi-stage build for production deployment
#
# Build: docker build -t arisp:latest -f deployment/docker/Dockerfile .
# Run: docker run -p 8000:8000 --env-file .env arisp:latest

# ============================================================================
# Stage 1: Builder
# ============================================================================
FROM python:3.10-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ============================================================================
# Stage 2: Production
# ============================================================================
FROM python:3.10-slim as production

# Labels
LABEL maintainer="ARISP Team"
LABEL version="1.0.0"
LABEL description="Automated Research Ingestion & Synthesis Pipeline"

# Create non-root user
RUN groupadd --gid 1000 arisp && \
    useradd --uid 1000 --gid arisp --shell /bin/bash --create-home arisp

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # PDF processing dependencies
    poppler-utils \
    # Health check tools
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY --chown=arisp:arisp src/ ./src/
COPY --chown=arisp:arisp config/ ./config/

# Create directories
RUN mkdir -p /app/output /app/.cache /app/logs && \
    chown -R arisp:arisp /app

# Switch to non-root user
USER arisp

# Environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Expose health endpoint port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/live || exit 1

# Default command: run scheduler with health server
CMD ["python", "-m", "src.cli", "schedule", "--health-port", "8000"]
