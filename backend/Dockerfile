# Base: Microsoft's Playwright image already has Chromium + all OS-level
# dependencies (fonts, libs) pre-installed. Matches the pinned Playwright
# version in requirements.txt — bump both together.
#
# The same image runs TWO services at runtime:
#   - FastAPI HTTP server           (CMD override: uvicorn app.main:app ...)
#   - Arq background-job worker     (CMD override: arq app.worker.WorkerSettings)
# docker-compose.prod.yml sets the command per service; this Dockerfile
# just produces one reusable image.

FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Don't buffer stdout/stderr — we want logs to reach docker/journald
# in real time, not at the end of the process.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Skip the Microsoft Playwright post-install browser download at pip
    # install time — the base image already shipped them.
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install Python deps first so a code change doesn't bust the layer
# cache that carries requirements.txt resolution.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy the app. Tests + alembic are needed at runtime for migrations;
# `.dockerignore` trims everything we don't want (venv, scans.db, caches).
COPY . .

# Run as a non-root user. The Playwright base image ships a `pwuser`
# with UID 1000 already configured for browser sandboxing — we reuse
# it rather than creating our own so Chromium's seccomp/namespace
# expectations still hold.
RUN chown -R pwuser:pwuser /app
USER pwuser

EXPOSE 8080

# Entry point runs migrations before the HTTP server so a fresh
# deploy self-bootstraps. The worker service in compose skips this
# (migrations are an HTTP-boot concern — worker starts AFTER the
# backend anyway and should never race the schema).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips=*"]
