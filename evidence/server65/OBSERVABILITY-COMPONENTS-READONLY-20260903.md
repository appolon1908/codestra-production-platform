# Observability component read-only inventory

Date: 2026-09-03
Target: `65.109.65.169`
Access: approved `codestra-app` operator; container metadata only.

Present and running:

- Prometheus
- Alertmanager
- Grafana
- Node Exporter
- cAdvisor/Redis/PostgreSQL exporters

No running Server 65 container matched the required log/trace collector or
agent roles: Loki, Tempo, Alloy/OpenTelemetry Collector, Promtail, Vector, or
Fluent Bit. The architecture permits central collectors on another host, but
their reachability and end-to-end log/trace propagation were not proven here.

OBSERVABILITY_COMPONENTS=FAIL
METRICS=PARTIAL
LOGS=FAIL
TRACES=FAIL
ALERTS=PARTIAL
APPLICATION_MONITORING=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
