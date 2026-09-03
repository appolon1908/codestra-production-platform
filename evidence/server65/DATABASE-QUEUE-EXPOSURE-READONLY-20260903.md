# Database and queue exposure read-only audit

Date: 2026-09-03
Target: `65.109.65.169`
Access: `codestra-app` / `codestra-admin`; Docker and socket inspection only.

## Findings

- No PostgreSQL or Redis container publishes a host port on `0.0.0.0`.
- The authority PostgreSQL and Redis bindings are loopback-only
  (`127.0.0.1:55434` and `127.0.0.1:56381`).
- NATS client and monitoring listeners are loopback-only
  (`127.0.0.1:4222` and `127.0.0.1:8222`).
- Public listeners observed are limited to Caddy/edge ports and the SSH port;
  no database or queue listener was observed on the public address.
- This proves network exposure posture only. It does not certify credentials,
  schema/migrations, durability, pooling, dead-letter behavior, retry, or
  isolated restore.

DATABASE_PUBLIC_EXPOSURE=PASS
DATABASES=FAIL
QUEUES=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
