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
- Backup: `FORMALLY_NOT_REQUIRED`; accountable owner Ralph Appolon approved the
  reconstructible-state policy during the 2026-08-26 production mission. Redis
  is not the durable business-state authority and the reviewed safe key count
  was zero.
- HA: `FORMALLY_NOT_REQUIRED` while Redis-dependent
  production activation flags remain disabled and all durable jobs are
  recoverable from PostgreSQL.
- Review: before enabling WebRTC, Redis runtime, social delivery, or any feature
  that makes Redis state non-reconstructible.
- Policy review date: 2026-11-24, or earlier on any dependent feature change.

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
