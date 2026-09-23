# Caddy configuration authority

This directory is the canonical Git home for Codestra's Server A Caddy desired
state. It owns public TLS, hostname routing, upstream selection, security
headers, request limits, credential-safe access logging, and edge health
behavior. Kong remains the API-policy authority behind Caddy.

Layout:

- `Caddyfile` is the reviewed import root.
- `snippets/` contains reusable, non-secret policy snippets.
- `*.caddy` contains complete hostname blocks.
- `klyrow-events.caddy` and `telnexa-events.caddy` are host-network fragments
  and are deliberately not imported by the container root; they may only be
  installed by the protected host-Caddy procedure after listener, upstream,
  and mTLS identity material are proven.

The tracked files contain no ACME account keys, certificates, DNS tokens, or
other secrets. Runtime material under `/etc/caddy` on `65.109.65.169` is a
deployment projection. A host operator must discover the active import path,
back it up, render these reviewed files into that path, run `caddy validate`,
and use a graceful reload. Editing a live container or an untracked host file
does not change source authority.

Server A runs Caddy as a Compose service. Container-to-container upstreams
therefore use shared-network DNS names such as `keycloak:8080`; loopback inside
the Caddy container must not be used for a different service.

The Middleware repository's `platform/caddy` branch owns integration review,
route compatibility, and edge tests. Production Caddy files and their release
digest are owned here and pinned by the platform release manifest.
