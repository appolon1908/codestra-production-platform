# Redis production policy

Redis is a private, authenticated coordination service. PostgreSQL remains the
durable authority for middleware inbox, outbox, delivery, callback, and social
jobs. Redis carries reconstructible wake-up signals, short-lived locks, streams,
and realtime coordination. It is not approved as the sole store for durable
business state.

## Recovery classification

- Classification: `RECONSTRUCTIBLE_STATE`, `QUEUES`, `LOCKS`, and
  `WEBSOCKET_STATE`.
- Owner: Ralph Appolon.
- Proposed RPO: 24 hours; active PostgreSQL state is authoritative.
- Proposed RTO: 60 minutes to reconstruct Redis coordination state.
- Backup: `FORMALLY_NOT_REQUIRED_PENDING_OWNER_APPROVAL` because Redis is not
  the durable business-state authority and the current safe key count is zero.
- HA: `FORMALLY_NOT_REQUIRED_PENDING_OWNER_APPROVAL` while Redis-dependent
  production activation flags remain disabled and all durable jobs are
  recoverable from PostgreSQL.
- Review: before enabling WebRTC, Redis runtime, social delivery, or any feature
  that makes Redis state non-reconstructible.

The runtime uses AOF plus RDB with `noeviction`. Reconstruction is: stop affected
workers, preserve the existing AOF/RDB for evidence, start an empty private Redis
instance from the locked configuration and ACL policy, replay durable work from
the PostgreSQL inbox/outbox authorities, reconnect application sessions, verify
queue and lock invariants, and then re-enable workers. No public port is opened.

The restricted monitoring identity is deliberately unable to invoke `BGSAVE`.
Do not broaden that ACL merely to create a backup. If an owner later classifies
Redis data as durable, introduce a separate reviewed backup identity and require
encrypted off-host backup plus isolated restore evidence before activation.

## Monitoring boundary

Redis remains on `codestra_backend`. The restricted exporter joins that backend
and the dedicated monitoring network. Prometheus stays only on the monitoring
network and scrapes the stable `redis-exporter:9121` alias. Exporter credentials
are supplied from a root-controlled secret file. Native `LATENCY` permission is
not required because exporter scrape duration, command duration/rate, application
Redis histograms, rejected connections, blocked clients, and slowlog counters
provide adequate latency signals without expanding ACL privileges.
