# Communication runtime trace and restore CI evidence

Date: 2026-09-03
Server scope: 65.109.65.169 (evidence only; no host mutation)

## Candidate source

- Repository: `appolon1908-hue/Codestra-Communication-CC`
- Pull request: https://github.com/appolon1908-hue/Codestra-Communication-CC/pull/6
- Exact candidate SHA: `77d7496ee8c23ccda1140c51a4625b2159c501e5`
- PR state: draft; not deployed

## Protected CI read-back

At the exact candidate SHA:

- `unit-and-contract`: PASS
- `postgres-certification`: PASS
- `container-build`: PASS
- active unresolved review threads: 0

The PostgreSQL certification job performs an isolated logical restore using a
digest-pinned PostgreSQL image. Its archive checksum is verified after copying
the archive and checksum into a separate filesystem directory. It compares the
semantic public schema inventory (columns, constraints, indexes) and complete
data-only dumps between source and restored databases.

## Trace controls covered by source tests

- Opt-in OTLP export (`TELEMETRY_EXPORT_ENABLED`, default `false`).
- Enabled exporter configuration accepts only HTTPS or loopback HTTP endpoints;
  credentials, query strings, and fragments are rejected.
- HTTP server spans accept W3C `traceparent`/`tracestate` and return only a
  bounded `X-Trace-ID` response header.
- Middleware client spans inject W3C context into downstream requests.
- Trace context is persisted in the encrypted durable delivery outbox and
  restored for worker dispatch.
- Span attributes are bounded method/status/host/correlation values; secrets
  and provider payloads are not emitted.
- Optional collector CA/client-mTLS files are validated as regular files; client
  keys must be runtime-owned and mode `0600`, and incomplete mTLS configuration
  fails closed.

## Certification boundary

This evidence proves source-level behavior and protected CI only. It does not
prove deployment, collector reachability, production backup/restore, staging
certification, or production readiness. Server 65 remains production blocked.

SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
