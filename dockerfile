# ───────────────────────────────────────────────────
# KINDpos Vz1.5 — Fly Dockerfile
# Base: official Python slim. Small, fast, predictable.
# ───────────────────────────────────────────────────

FROM python:3.11-slim

# System deps. tini = proper PID-1 signal handling so Ctrl-C / fly restarts
# gracefully shut the app down. Minimal package set to keep image small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/*

# App lives at /app. Fly's [mounts] section mounts a volume at /data so the
# SQLite event ledger persists across deploys — keep /data separate from /app.
WORKDIR /app

# Python runtime hygiene
# PYTHONPATH=/app/backend is critical: backend/app/main.py uses bare imports
# like `from app.api.routes.printing import ...` which only resolve when
# backend/ is on the Python path. That's how it runs locally too.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/backend

# Install Python deps FIRST (layer cache friendly — deps rarely change).
# requirements.txt lives at backend/requirements.txt in this repo.
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

# Copy the app source. We copy backend/ and terminal/ explicitly so the image
# doesn't pick up node_modules, .venv, test fixtures, etc. Add more dirs here
# if your backend references them (migrations/, scripts/, data/seed/, etc.).
COPY backend/  ./backend/
COPY terminal/ ./terminal/

# Fly's [http_service] routes to internal_port 8080. Must match.
EXPOSE 8080

# CMD: uvicorn target is `app.main:app` because backend/ is on PYTHONPATH,
# so `app` = the app package at /app/backend/app. Do NOT write it as
# `backend.app.main:app` — that breaks the bare `app.xxx` imports inside.
# CWD stays at /app (repo root) so relative paths like "terminal" in
# StaticFiles resolve to /app/terminal.
ENTRYPOINT ["/usr/bin/tini", "-s", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]