# Observability

`/metrics` exports event states and dependency circuit state in Prometheus format. Structured HTTP logs identify system/client without secrets. Correlation timelines join cross-system operations. Extend the existing private Prometheus stack to scrape `127.0.0.1:8096/metrics` and alert on readiness=0, DLQ>0, sustained queue growth, retry ratio, open circuits, and dependency latency/error SLOs.
