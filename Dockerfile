# ============================================================
# MCP Central — Multi-stage Dockerfile
# Stage 1: Build the React frontend
# Stage 2: Install Python dependencies
# Stage 3: Final minimal runtime image
# ============================================================

# ---- Stage 1: Frontend build --------------------------------
FROM node:20-slim AS frontend-builder

WORKDIR /build/frontend

# Install pnpm
RUN npm install -g pnpm@10

# Install dependencies
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Build
COPY frontend/ ./
RUN pnpm build


# ---- Stage 2: Python dependency install ---------------------
FROM python:3.12-slim AS python-builder

WORKDIR /build

# Install uv
RUN pip install --no-cache-dir uv

# Copy project metadata only first (cache layer)
COPY pyproject.toml ./

# Install all production dependencies into a venv
RUN uv venv /build/.venv --python python3.12 && \
    uv pip install --no-cache ".[dev]" --python /build/.venv/bin/python

# Copy full source for the venv to reference
COPY hub/ ./hub/


# ---- Stage 3: Runtime ---------------------------------------
FROM python:3.12-slim AS runtime

# Install system runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    tinyproxy \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -g 1000 mcpcentral && \
    useradd -u 1000 -g mcpcentral -m -s /bin/bash mcpcentral

WORKDIR /app

# Copy the Python venv from builder
COPY --from=python-builder /build/.venv /app/.venv

# Server packages may be uv projects with pyproject.toml/uv.lock metadata.
COPY --from=python-builder /usr/local/bin/uv /usr/local/bin/uv

# Copy application source
COPY hub/ /app/hub/
COPY docs/ /app/docs/
COPY alembic.ini /app/

# Copy built frontend
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist

# Copy entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create persistent data directories
RUN mkdir -p /app/data/logs /app/servers && \
    chown -R mcpcentral:mcpcentral /app/data /app/servers

# Switch to non-root user
USER mcpcentral

# Make the venv's Python/scripts available
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
