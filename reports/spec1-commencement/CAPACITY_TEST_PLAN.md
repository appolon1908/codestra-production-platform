# Capacity test plan

No PSTN traffic is permitted. Use synthetic SIP/media and tenant-separated data.

Human design target: 20 concurrent authenticated agent sessions, state changes,
screen-pop events and manual internal calls. AI design target: 100 synthetic
media sessions through isolated edge/gateway fixtures with business tools mocked
behind middleware authorization.

Measure p50/p95/p99 API latency, error rate, PostgreSQL locks, reservation
contention, Redis/NATS throughput, consumer lag, Odoo worker saturation, adapter
spool, CPU/memory/network, audio jitter/loss, storage throughput and failover
recovery. Preapproved thresholds and spend/provider quotas are mandatory before
execution. Passing capacity does not authorize production concurrency.
