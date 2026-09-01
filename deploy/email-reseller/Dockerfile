FROM python@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df
ARG VCS_REF
ARG SOURCE_URL=https://github.com/appolon1908-hue/codestra-production-platform
ARG VERSION
LABEL org.opencontainers.image.revision=$VCS_REF org.opencontainers.image.source=$SOURCE_URL org.opencontainers.image.version=$VERSION
RUN apk upgrade --no-cache && pip install --no-cache-dir psycopg[binary]==3.2.9
WORKDIR /app
COPY email_reseller_service /app/email_reseller_service
RUN addgroup -S codestra && adduser -S -G codestra codestra && mkdir /data && chown codestra:codestra /data
USER codestra
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "email_reseller_service.server"]
