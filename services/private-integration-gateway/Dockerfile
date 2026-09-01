FROM python:3.12.14-alpine3.24@sha256:1887c114801a8c82a4ec01daa52cfe7fc3f63573640e2247320289807ac1c3bb

ARG SOURCE_COMMIT_SHA
RUN test -n "${SOURCE_COMMIT_SHA}" \
    && addgroup -g 10001 gateway \
    && adduser -D -u 10001 -G gateway gateway \
    && install -d -o 10001 -g 10001 -m 0700 /data

LABEL org.opencontainers.image.source="https://github.com/appolon1908-hue/codestra-production-platform" \
      org.opencontainers.image.revision="${SOURCE_COMMIT_SHA}" \
      org.opencontainers.image.title="Codestra private integration gateway"

WORKDIR /app
COPY --chown=10001:10001 --chmod=0555 gateway.py /app/gateway.py

USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD ["python", "-I", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()"]
ENTRYPOINT ["python", "-I", "-u", "/app/gateway.py"]
