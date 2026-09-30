# Build context = repo root. One image serves the API + built PWA, and runs the worker.
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS server
COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY server/ ./
RUN uv sync --frozen --no-dev
COPY content/ /content/
COPY --from=web /web/dist /web_dist
ENV PATH="/app/.venv/bin:$PATH" \
    EHNGLISH_CONTENT_DIR=/content \
    EHNGLISH_WEB_DIST=/web_dist \
    EHNGLISH_RAW_DIR=/data/raw
EXPOSE 3305
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 3305 --proxy-headers --forwarded-allow-ips='*'"]
