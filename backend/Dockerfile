FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime libraries the OpenCascade / VTK wheels link against (no X server is used).
# Optional corporate CA for TLS-inspecting proxies (never persisted in a layer):
#   docker build --secret id=corp_ca,src=/path/to/ca.crt ...
RUN --mount=type=secret,id=corp_ca,required=false,mode=0444 \
    set -eu; \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    APT_CA=""; if [ -s /run/secrets/corp_ca ]; then APT_CA="-o Acquire::https::CAInfo=/run/secrets/corp_ca"; fi; \
    apt-get $APT_CA update; \
    apt-get $APT_CA install -y --no-install-recommends libgl1 libglu1-mesa libxrender1 libxext6 libx11-6 libxi6 \
        libxcursor1 libxft2 libxinerama1 libfontconfig1; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd --system --gid 10001 quote; \
    useradd --system --uid 10001 --gid quote --home /app --shell /usr/sbin/nologin quote

WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=corp_ca,required=false \
    if [ -s /run/secrets/corp_ca ]; then export PIP_CERT=/run/secrets/corp_ca; fi; \
    pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts
RUN python -c "import OCP.STEPControl, app.main" \
 && mkdir -p /data && chown quote:quote /data

USER quote
ENV QUOTE_ENVIRONMENT=production \
    QUOTE_DATABASE_PATH=/data/quotes.sqlite3 \
    FORWARDED_ALLOW_IPS=127.0.0.1 \
    WEB_CONCURRENCY=2
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

# --proxy-headers + FORWARDED_ALLOW_IPS: trust X-Forwarded-For only from the reverse proxy.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\" --workers \"$WEB_CONCURRENCY\" --no-server-header"]
