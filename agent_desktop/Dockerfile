FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS build
ARG VCS_REF=unknown
WORKDIR /app
COPY package*.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY . .
RUN npm run build
FROM caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d
ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/appolon1908-hue/codestra-production-platform" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.title="Codestra Agent Desktop"
RUN setcap -r /usr/bin/caddy
COPY --from=build /app/dist /usr/share/caddy
COPY Caddyfile /etc/caddy/Caddyfile
USER caddy
