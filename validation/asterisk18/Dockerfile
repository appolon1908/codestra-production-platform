FROM debian:bookworm-20260623-slim@sha256:60eac759739651111db372c07be67863818726f754804b8707c90979bda511df AS build

ARG ASTERISK_VERSION=18.26.4
ARG ASTERISK_SHA256=a17f511bfa092c8fa9eccd3a5ecf5f728ccdcf2b1a04d2c06e7177d96c3c9ee1
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl libedit-dev libjansson-dev libssl-dev \
    libsqlite3-dev libxml2-dev uuid-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl --fail --show-error --location --proto '=https' --tlsv1.2 \
      -o asterisk.tar.gz \
      "https://downloads.asterisk.org/pub/telephony/asterisk/releases/asterisk-${ASTERISK_VERSION}.tar.gz" \
    && echo "${ASTERISK_SHA256}  asterisk.tar.gz" | sha256sum --check - \
    && tar -xzf asterisk.tar.gz --strip-components=1 \
    && ./configure --with-jansson-bundled=no \
    && make menuselect.makeopts \
    && menuselect/menuselect --disable BUILD_NATIVE --enable res_manager_devicestate menuselect.makeopts \
    && make -j2 \
    && make DESTDIR=/stage install

FROM debian:bookworm-20260623-slim@sha256:60eac759739651111db372c07be67863818726f754804b8707c90979bda511df
ARG ASTERISK_VERSION=18.26.4
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libedit2 libjansson4 libssl3 libsqlite3-0 libxml2 socat tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 asterisk \
    && useradd --system --uid 10001 --gid asterisk --home /var/lib/asterisk asterisk
COPY --from=build /stage/usr/ /usr/
COPY --from=build /stage/var/lib/asterisk/ /asterisk-seed/
COPY --from=build /stage/var/spool/asterisk/ /var/spool/asterisk/
COPY config/asterisk.conf config/extensions.conf config/logger.conf config/modules.conf /etc/asterisk/
COPY scripts/container-entrypoint.sh /usr/local/bin/container-entrypoint
RUN chmod 0755 /usr/local/bin/container-entrypoint \
    && mkdir -p /var/lib/asterisk /var/log/asterisk /var/run/asterisk /var/spool/asterisk \
    && chown -R asterisk:asterisk /etc/asterisk /var/lib/asterisk /var/log/asterisk \
      /var/run/asterisk /var/spool/asterisk
LABEL org.opencontainers.image.version="${ASTERISK_VERSION}" \
      org.opencontainers.image.description="Disposable CI-only Asterisk 18 AMI validation harness"
EXPOSE 5038 5039 5040 5041 5042 5043
ENTRYPOINT ["/usr/bin/tini","--","/usr/local/bin/container-entrypoint"]
