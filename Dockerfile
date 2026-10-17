FROM python:3.12.15-alpine3.24 AS builder
WORKDIR /build
COPY requirements.txt requirements.lock ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.12.15-alpine3.24 AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/auctions.db
WORKDIR /app
RUN apk upgrade --no-cache \
    && addgroup -g 10001 auction \
    && adduser -D -H -u 10001 -G auction auction \
    && mkdir /data && chown auction:auction /data
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
ARG VCS_REF
RUN python -c 'import json,re,sys; revision=sys.argv[1]; assert re.fullmatch("[0-9a-f]{40}", revision), "VCS_REF must be a full SHA"; open("app/build_info.json", "w").write(json.dumps({"revision": revision}))' "$VCS_REF"
LABEL org.opencontainers.image.revision=$VCS_REF \
    org.opencontainers.image.source="https://github.com/nopopjustrap/devops_auction"
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
