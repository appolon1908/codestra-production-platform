FROM python@sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a
ARG VCS_REF
ARG SOURCE_URL=https://github.com/appolon1908-hue/codestra-production-platform
ARG VERSION
LABEL org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.source=$SOURCE_URL org.opencontainers.image.version=$VERSION
ENV CODESTRA_GIT_SHA=$VCS_REF CODESTRA_APPLICATION_VERSION=$VERSION
RUN apk upgrade --no-cache && pip install --no-cache-dir psycopg[binary]==3.2.9
WORKDIR /app
COPY email_reseller_service /app/email_reseller_service
RUN addgroup -S codestra && adduser -S -G codestra codestra && mkdir /data && chown codestra:codestra /data
USER codestra
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "email_reseller_service.server"]
