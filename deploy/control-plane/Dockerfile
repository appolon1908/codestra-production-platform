FROM python:3.12.11-slim-bookworm
RUN python -m pip install --no-cache-dir --upgrade pip==26.2 \
 && python -m pip install --no-cache-dir psycopg[binary]==3.2.9
RUN useradd --system --uid 10001 controlplane && mkdir /data && chown 10001:10001 /data
WORKDIR /app
COPY control_plane_service /app/control_plane_service
USER 10001
HEALTHCHECK --interval=20s --timeout=3s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8096/health')"
CMD ["python", "-m", "control_plane_service.server"]
