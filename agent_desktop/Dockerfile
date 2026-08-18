FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS build
ARG VCS_REF=unknown
WORKDIR /app
COPY package*.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY . .
RUN npm run build
FROM golang:1.26-alpine@sha256:3889b425f035be855a72fb4755265311293b6d414521f0a519d819df32222d83 AS caddy-build
WORKDIR /src
RUN go mod init codestra.invalid/caddy-build \
 && go get github.com/caddyserver/caddy/v2/cmd/caddy@v2.11.4 \
 && go get golang.org/x/net@v0.56.0 golang.org/x/text@v0.39.0 google.golang.org/grpc@v1.82.1 \
 && CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /caddy github.com/caddyserver/caddy/v2/cmd/caddy

FROM alpine:3.24
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/appolon1908-hue/codestra-production-platform" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.title="Codestra Agent Desktop"
RUN apk upgrade --no-cache \
 && addgroup -S -g 10001 caddy \
 && adduser -S -D -H -u 10001 -G caddy caddy
COPY --from=caddy-build /caddy /usr/bin/caddy
COPY --from=build /app/dist /usr/share/caddy
COPY Caddyfile /etc/caddy/Caddyfile
USER caddy
