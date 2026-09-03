# NATS queue durability read-only probe

Date: 2026-09-03
Target: `65.109.65.169` authority NATS monitor (`127.0.0.1:8222`)
Access: monitoring GETs only (`/varz`, `/jsz`, `/connz`); no publish/subscribe.

- NATS version: `2.14.3`
- JetStream configured: strict mode, file store `/data/nats/jetstream`
- JetStream max memory: 1 GiB
- JetStream max storage: 10 GiB
- JetStream streams: `0`
- JetStream consumers: `0`
- Current client connections: `0`
- JetStream storage currently used: `0`
- NATS API errors: `0`

JetStream is configured but has no streams or consumers, so durable queue
contracts, retry/dead-letter behavior, lease/claim semantics, and persistence
are not proven for production workloads. No message was sent.

NATS_PROCESS=PASS
QUEUES=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
