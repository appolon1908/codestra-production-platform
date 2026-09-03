# Prometheus target and rule read-only audit

Date: 2026-09-03
Target: `65.109.65.169` Prometheus container network
Access: container-network HTTP GETs only; no credentials or configuration writes.

- Active scrape targets: `34`
- Targets reporting `up`: `34`
- Targets reporting `down`: `0`
- Alert rule groups loaded: `34`
- Alerting rules loaded: `232`
- Jobs observed include middleware runtimes, mail API, reseller portal,
  operations dashboard (production and staging), node, containers, Redis,
  PostgreSQL exporter, Prometheus, and blackbox probes.

This proves current Prometheus target responsiveness and rule loading. It does
not prove that all 20 runtime OpenAPI applications have complete health,
readiness, metrics, logs, traces, and owned alert coverage; staging targets are
also still present.

PROMETHEUS_TARGETS=PASS
APPLICATION_MONITORING=FAIL
OBSERVABILITY=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
