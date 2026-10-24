# Springform: one process, data in /data, HTTP on 8000, health at /up.

# SQLite >= 3.51.3 is required (the WAL-reset corruption fix) and Debian ships older, so build
# the pinned amalgamation as a shared library for the stdlib sqlite3 module to load. Built on the
# runtime base so the glibc matches. JSON is built in by default; FTS5 is switched on here.
FROM python:3.12-slim AS sqlite
ARG SQLITE_VERSION=3.51.3
ARG SQLITE_URL=https://sqlite.org/2026/sqlite-autoconf-3510300.tar.gz
ARG SQLITE_SHA256=81f5be397049b0cae1b167f2225af7646fc0f82e4a9b3c48c9ea3a533e21d77a
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN curl -fsSLo sqlite.tar.gz "$SQLITE_URL" \
    && echo "$SQLITE_SHA256  sqlite.tar.gz" | sha256sum -c - \
    && tar -xzf sqlite.tar.gz --strip-components=1 \
    && gcc -O2 -fPIC -shared -Wl,-soname,libsqlite3.so.0 -DSQLITE_ENABLE_FTS5 \
        sqlite3.c -o libsqlite3.so.0 -lm
COPY scripts/check-sqlite.py /usr/local/bin/
RUN LD_LIBRARY_PATH=/build python /usr/local/bin/check-sqlite.py "$SQLITE_VERSION"

# The Vite build reads backend/apps/*/app.json, so the apps folder comes along.
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
COPY backend/apps/ /src/backend/apps/
RUN npm run build

FROM python:3.12-slim
ARG SQLITE_VERSION=3.51.3
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH=/app/.venv/bin:$PATH \
    DATA_DIR=/data SPRINGFORM_REQUIRE_SQLITE=1
# The base image already carries tzdata and setpriv; check-sqlite.py asserts zoneinfo works.
COPY --from=sqlite /build/libsqlite3.so.0 /usr/local/lib/
COPY scripts/check-sqlite.py /usr/local/bin/
RUN ldconfig && python /usr/local/bin/check-sqlite.py "$SQLITE_VERSION" \
    && useradd --system --user-group --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /data
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
# The app runs from source (uvicorn puts /app on sys.path), so the project itself isn't installed.
RUN uv sync --frozen --no-dev --no-install-project
COPY springform-version ./
COPY backend/ backend/
COPY --from=frontend /src/frontend/dist/ frontend/dist/
COPY entrypoint.sh /usr/local/bin/

# No USER line: entrypoint.sh starts as root to chown /data, then drops to `app`.
VOLUME /data
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/up' % os.environ.get('PORT', '8000'), timeout=4)"
ENTRYPOINT ["entrypoint.sh"]
