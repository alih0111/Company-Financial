FROM node:22-bookworm-slim AS frontend
WORKDIR /build/client
COPY client/package.json client/package-lock.json client/.npmrc ./
RUN npm ci
COPY client/ ./
RUN npm run build

FROM golang:1-bookworm AS backend
WORKDIR /build/go-app
COPY go-app/go.mod go-app/go.sum ./
RUN go mod download
COPY go-app/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /rfa .

FROM python:3.13-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    TZ=Asia/Tehran PORT=5000 HOST=0.0.0.0 \
    FRONTEND_DIR=/app/client/dist PUBLIC_ARTIFACTS_DIR=/app/client/public CDF_PYTHON=/opt/venv/bin/python \
    PATH="/opt/venv/bin:$PATH" PYTHONPATH=/app:/app/go-app/py2/src
RUN apt-get update && apt-get install -y --no-install-recommends unixodbc ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv
COPY deploy/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /root/.cache/ms-playwright \
    && mv /root/.cache/ms-playwright /opt/ms-playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN groupadd --gid 10001 rfa && useradd --uid 10001 --gid rfa --create-home rfa
WORKDIR /app
# .dockerignore allows application source and public assets only; local accounts,
# research inputs, databases, browser profiles and credentials never enter images.
COPY --chown=rfa:rfa . /app/
COPY --from=frontend --chown=rfa:rfa /build/client/dist /app/client/dist
COPY --from=backend /rfa /usr/local/bin/rfa
RUN mkdir -p /app/.runtime /app/go-app/.runtime /app/ranking_research/output \
    && chown -R rfa:rfa /app
USER rfa
WORKDIR /app/go-app
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=8s --start-period=30s --retries=3 CMD ["rfa", "healthcheck"]
CMD ["rfa"]
