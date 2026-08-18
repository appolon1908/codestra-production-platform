# Python 3.12.13 / Alpine 3.24 (Docker Official Image).
ARG PYTHON_BASE=docker.io/library/python@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df
ARG VCS_REF=unknown
ARG BUILD_REVISION=unknown
ARG BUILD_CREATED=unknown

FROM ${PYTHON_BASE} AS python-builder
USER root
ARG PYTHON_SOURCE_SHA256=c08bc65a81971c1dd5783182826503369466c7e67374d1646519adf05207b684
WORKDIR /usr/src
RUN apk add --no-cache \
      build-base=0.5-r4 \
      bzip2-dev=1.0.8-r6 \
      curl=8.21.0-r0 \
      expat-dev=2.8.2-r0 \
      gdbm-dev=1.26-r0 \
      libffi-dev=3.5.2-r1 \
      linux-headers=7.0.0-r1 \
      ncurses-dev=6.6_p20260516-r0 \
      openssl-dev=3.5.7-r0 \
      patch=2.8-r0 \
      readline-dev=8.3.3-r1 \
      sqlite-dev=3.53.2-r0 \
      tar=1.35-r5 \
      xz-dev=5.8.3-r0 \
      zlib-dev=1.3.2-r0
COPY security/python312/*.patch /usr/src/patches/
RUN curl --fail --location --proto '=https' --tlsv1.2 \
      --output Python-3.12.13.tar.xz \
      https://www.python.org/ftp/python/3.12.13/Python-3.12.13.tar.xz \
 && echo "${PYTHON_SOURCE_SHA256}  Python-3.12.13.tar.xz" | sha256sum -c - \
 && mkdir upstream-patches \
 && while read -r commit checksum; do \
      curl --fail --location --proto '=https' --tlsv1.2 \
        --output "upstream-patches/${commit}.patch" \
        "https://github.com/python/cpython/commit/${commit}.patch"; \
      echo "${checksum}  upstream-patches/${commit}.patch" | sha256sum -c -; \
    done <<'PATCHES'
be13e86f6b9788a6f4d0419dffef72cbae5865c9 7c6208f7240f632779d6b1b33d20f90126888cc4ec9f636abeaa68b5dc875094
7f0dc59c9a70f8f3b4da33d7c4a2ba552a7acc21 f583351faf1f288bf10b6c3d5f4752cd4a17da881b0043e4eff6395ea7a199f6
7933f4bf7131aa4140750f9404f5de0aa2969ced d8913b46e769704d0e810994909ee81c8af6aaa7230b79ff4c0d849fe1f305a4
dae4b1a21f8df4570e30986affd61bbe4ade4cef da243766f48c8f78cc292559df5baedab3046ffcee3f754fb716b27e13952a7c
642865ddf4b232da1f3b1f7abcfa3254c4bfe785 afcdbd51c751170f703451aef3cfdd40a61bce2c05180cfcf87ff19c2c99f865
e20c6c9667c99ecaab96e1a2b3767082841ffc8b 7536be971df7f8b7ee9b4d6448edc6be11ed2b54f87531a61401542e10d60795
938ec030e90c5e53f1faac6fab1643f14e4f4a79 643e4385aeb14de75172f4e0f9dc5116934260cbb844d8b9d648545706f340fa
fc9b11ff49cbc82e6f917d07a61517a2b5f3145f e24d1474438cce8df94b8b5e336599326956e6f8cc1cf211932349230fd3ef28
PATCHES
RUN tar -xJf Python-3.12.13.tar.xz \
 && awk 'found || index($0, "diff --git a/Include/pyexpat.h") == 1 { found=1; print }' \
      upstream-patches/fc9b11ff49cbc82e6f917d07a61517a2b5f3145f.patch \
      > upstream-patches/fc9b11ff49cbc82e6f917d07a61517a2b5f3145f-3.12-rest.patch \
 && cd Python-3.12.13 \
 && for patch_file in \
      ../upstream-patches/be13e86f6b9788a6f4d0419dffef72cbae5865c9.patch \
      ../upstream-patches/7f0dc59c9a70f8f3b4da33d7c4a2ba552a7acc21.patch \
      ../upstream-patches/7933f4bf7131aa4140750f9404f5de0aa2969ced.patch \
      ../upstream-patches/dae4b1a21f8df4570e30986affd61bbe4ade4cef.patch \
      ../upstream-patches/642865ddf4b232da1f3b1f7abcfa3254c4bfe785.patch \
      ../upstream-patches/e20c6c9667c99ecaab96e1a2b3767082841ffc8b.patch \
      ../upstream-patches/938ec030e90c5e53f1faac6fab1643f14e4f4a79.patch \
      ../upstream-patches/fc9b11ff49cbc82e6f917d07a61517a2b5f3145f-3.12-rest.patch \
      ../patches/webbrowser-action-hardening.patch \
      ../patches/expat-hash-salt-3.12.patch; do \
        patch -p1 --batch < "${patch_file}"; \
    done \
 && ./configure \
      --enable-loadable-sqlite-extensions \
      --enable-option-checking=fatal \
      --enable-shared \
      --with-ensurepip \
      --with-system-expat \
 && make -j"$(nproc)" \
 && make install

FROM ${PYTHON_BASE} AS patched-python
USER root
RUN apk add --no-cache expat=2.8.2-r0
RUN rm -rf /usr/local/*
COPY --from=python-builder /usr/local /usr/local

FROM patched-python AS builder
ARG VCS_REF
ARG BUILD_REVISION
ARG BUILD_CREATED
LABEL org.opencontainers.image.source="https://github.com/appolon1908-hue/codestra-production-platform" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_CREATED}" \
      io.codestra.build.revision="${BUILD_REVISION}" \
      io.codestra.python.base.repository="docker.io/library/python" \
      io.codestra.python.base.digest="sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df" \
      io.codestra.python.version="3.12.13"
USER root
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.lock requirements-test.lock ./
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
      --require-hashes -r requirements.lock

FROM builder AS test
RUN apk add --no-cache bash=5.3.9-r1 git=2.54.0-r0 openssl=3.5.7-r0
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
      --require-hashes -r requirements-test.lock
WORKDIR /app
COPY --chown=10001:10001 . /app
ENV PYTHONPATH=/app
USER 10001:10001
ENTRYPOINT ["pytest"]

FROM patched-python AS runtime
ARG VCS_REF
ARG BUILD_REVISION
ARG BUILD_CREATED
LABEL org.opencontainers.image.source="https://github.com/appolon1908-hue/codestra-production-platform" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_CREATED}" \
      io.codestra.build.revision="${BUILD_REVISION}" \
      io.codestra.python.base.repository="docker.io/library/python" \
      io.codestra.python.base.digest="sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df" \
      io.codestra.python.version="3.12.13"
USER root
RUN grep -q '^app:' /etc/group || addgroup -S -g 10001 app \
 && grep -q '^app:' /etc/passwd || adduser -S -D -H -u 10001 -G app app
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=10001:10001 alembic.ini app.py ./
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 schemas ./schemas
COPY --chown=10001:10001 scripts ./scripts
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8095
CMD ["python", "-m", "app.entrypoints.integration_api"]

FROM patched-python AS qwen-auth-verifier-runtime
ARG VCS_REF
ARG BUILD_REVISION
LABEL org.opencontainers.image.title="Codestra Qwen Authentication Verifier" \
      org.opencontainers.image.description="Read-only private mTLS and HMAC authentication verifier" \
      org.opencontainers.image.source="https://github.com/Codestra-SRL/codestra-middleware" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="1.0.0-rc1" \
      io.codestra.build.revision="${BUILD_REVISION}" \
      io.codestra.python.base.repository="docker.io/library/python" \
      io.codestra.python.base.digest="sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df" \
      io.codestra.python.version="3.12.13"
USER root
RUN grep -q '^app:' /etc/group || addgroup -S -g 10001 app \
 && grep -q '^app:' /etc/passwd || adduser -S -D -H -u 10001 -G app app
COPY --from=builder /opt/venv /opt/venv
RUN /opt/venv/bin/python -m pip uninstall -y \
      alembic asyncpg greenlet httpcore httpx mako markupsafe prometheus-client \
      pyjwt python-dotenv redis sqlalchemy pydantic-settings \
 && /opt/venv/bin/python -m pip uninstall -y pip setuptools
WORKDIR /app
COPY --chown=10001:10001 app/qwen_auth_verifier.py /app/app/qwen_auth_verifier.py
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8095
CMD ["uvicorn", "app.qwen_auth_verifier:create_app", "--factory", "--host", "0.0.0.0", "--port", "8095", "--no-server-header", "--no-date-header"]
