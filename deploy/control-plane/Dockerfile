ARG CHAINGUARD_PYTHON_DEV=cgr.dev/chainguard/python@sha256:4bf7e945777010672b8ccd5d2ae2c41c91ad6d3478878347c731ae536d506bef
ARG CHAINGUARD_PYTHON_RUNTIME=cgr.dev/chainguard/python@sha256:1f6779775c9f466890da563e411cb677045a6c20b6a65160eefad1deffb5012c

FROM ${CHAINGUARD_PYTHON_DEV} AS builder
USER root
RUN python -m venv /opt/venv \
 && /opt/venv/bin/python -m pip install --no-cache-dir --disable-pip-version-check \
      'psycopg[binary]==3.3.4' \
 && /opt/venv/bin/python -m pip uninstall -y pip setuptools wheel \
 && mkdir /data

FROM ${CHAINGUARD_PYTHON_RUNTIME}
ARG VCS_REF=unknown
ARG BUILD_CREATED=unknown
LABEL org.opencontainers.image.source="https://github.com/appolon1908-hue/codestra-production-platform" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_CREATED}" \
      io.codestra.python.base.repository="cgr.dev/chainguard/python" \
      io.codestra.python.base.digest="sha256:1f6779775c9f466890da563e411cb677045a6c20b6a65160eefad1deffb5012c"
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=10001:10001 /data /data
WORKDIR /app
COPY --chown=10001:10001 control_plane_service /app/control_plane_service
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001:10001
HEALTHCHECK --interval=20s --timeout=3s --retries=5 CMD ["/opt/venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8096/health')"]
CMD ["/opt/venv/bin/python", "-m", "control_plane_service.server"]
