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
ARG SOURCE_URL=https://github.com/appolon1908-hue/codestra-production-platform
ARG VERSION=unknown
LABEL org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.source=$SOURCE_URL org.opencontainers.image.version=$VERSION
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=10001:10001 /data /data
WORKDIR /app
COPY --chown=10001:10001 email_reseller_service /app/email_reseller_service
ENV PATH=/opt/venv/bin:$PATH PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    CODESTRA_GIT_SHA=$VCS_REF CODESTRA_APPLICATION_VERSION=$VERSION
USER 10001:10001
ENTRYPOINT ["/opt/venv/bin/python"]
CMD ["-m", "email_reseller_service.server"]
