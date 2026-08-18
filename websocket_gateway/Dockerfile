FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/appolon1908-hue/codestra-production-platform" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.title="Codestra WebSocket Gateway"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 codestra && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin codestra
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
 && pip uninstall -y pip setuptools wheel
COPY app.py migrate.py ./
COPY migrations ./migrations
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--ws-ping-interval", "25", "--ws-ping-timeout", "10", "--timeout-graceful-shutdown", "10", "--no-access-log"]
