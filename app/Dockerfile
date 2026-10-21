# aikos app image: the PWA built with Node, served by the Python service. Base images pinned by digest.
# Build from the app folder:  docker build --build-arg AIKOS_APP_COMMIT=$(git rev-parse HEAD) -t aikos-app .

FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-trixie@sha256:2259debdc6af85626058a15a7bf44ad6a68b8c98c9ae82a02cf5cdb92f096d47
ARG AIKOS_APP_COMMIT=dev
LABEL org.opencontainers.image.source="https://github.com/aikos-home/aikos" \
      org.opencontainers.image.description="aikos app: the household's user interface in front of Home Assistant" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision="${AIKOS_APP_COMMIT}"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AIKOS_APP_COMMIT=${AIKOS_APP_COMMIT} AIKOS_APP_WEB_DIR=/srv/web AIKOS_APP_DATA_DIR=/data
RUN useradd --system --uid 10001 --home-dir /srv --shell /usr/sbin/nologin aikos \
 && mkdir -p /data && chown aikos /data
WORKDIR /srv
COPY requirements.lock ./
RUN pip install --require-hashes --no-deps -r requirements.lock
# The service runs from its source folder (/srv is the working directory); no build step, no unpinned build tools.
COPY aikos_app ./aikos_app
COPY --from=web /web/dist /srv/web
USER aikos
EXPOSE 8780
HEALTHCHECK --interval=15s --timeout=4s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('AIKOS_APP_PORT','8780') + '/api/v1/health', timeout=3)"
CMD ["python", "-m", "aikos_app"]
