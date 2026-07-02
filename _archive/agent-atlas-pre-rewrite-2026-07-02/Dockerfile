# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime ────────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Copy config (can be overridden by volume mount in docker-compose)
COPY config/ ./config/

# Copy built frontend (FastAPI serves it at /)
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

# Persistent data directories (mount a volume at /app/data in production)
RUN mkdir -p /app/data/db /app/data/embeddings /app/data/traces /app/data/exports

ENV PYTHONPATH=/app/backend
ENV PORT=8000

EXPOSE 8000

# Run with uvicorn — PORT env var supported by Railway/Fly.io
CMD python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
