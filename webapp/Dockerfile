# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data HOST=0.0.0.0 PORT=8080 CHROMIUM_EXECUTABLE=/usr/bin/chromium
RUN apt-get update && apt-get install -y --no-install-recommends chromium ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app && mkdir -p /data && chown app:app /data
WORKDIR /app
COPY requirements.lock ./
# Optional combined CA bundle for managed build proxies; never stored in the image.
RUN --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export PIP_CERT=/run/secrets/system_ca; fi; \
    python -m pip install --no-cache-dir --require-hashes -r requirements.lock
COPY --chown=app:app app ./app
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app"]
