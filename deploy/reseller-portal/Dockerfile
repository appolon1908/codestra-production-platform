FROM python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
ARG VCS_REF
ARG SOURCE_URL=https://github.com/appolon1908-hue/codestra-production-platform
ARG VERSION
LABEL org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.source=$SOURCE_URL org.opencontainers.image.version=$VERSION
WORKDIR /app
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libpcre2-8-0=10.42-1+deb12u1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi==0.141.1 starlette==1.6.0 uvicorn==0.52.4 psycopg[binary]==3.2.9 prometheus-client==0.22.1
COPY reseller_portal /app/reseller_portal
USER 65532:65532
CMD ["uvicorn","reseller_portal.app:app","--host","0.0.0.0","--port","8080","--no-server-header"]
