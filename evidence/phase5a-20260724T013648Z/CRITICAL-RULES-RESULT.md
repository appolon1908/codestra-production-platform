# Critical alert rules result

`CRITICAL_ALERT_RULE_GATE=PASS`

The authoritative catalog contains 66 required critical alert classes and 10 warning companions (76 rules total). Every critical rule has `alertname`, `severity`, `service`, `environment`, `owner_ref`, summary, actionable description, current value, threshold, candidate-tuning status, runbook URL, and dashboard/evidence reference.

Validation:

- Prometheus `promtool`: PASS, one rule file and 76 rules.
- Rule coverage and required annotations: PASS, 66/66.
- Duplicate alert names: PASS, zero duplicates.
- Warning/critical distinction: PASS for capacity, latency, backlog, TLS, and restore-age controls.

No threshold is represented as production-proven. No monitoring stack or receiver was deployed.
