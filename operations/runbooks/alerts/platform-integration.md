# Platform integration monitoring

The private core probes use GET only. No workflow execution, dialing, mail, SMS,
lead mutation, database write, or public metrics exposure is part of a probe.

| Application | Target | Evidence provided |
| --- | --- | --- |
| Odoo | `codestra-odoo-1:8069/web/health` | HTTP process liveness; this does not certify Odoo ORM, outbox, or business transactions |
| n8n | `codestra-n8n-1:5678/healthz/readiness` | n8n readiness including its database |
| Middleware | `codestra-middleware-1:8095/readyz` | The installed runtime's readiness contract; disabled dependencies remain disabled |
| VICIdial integration | `middleware-vicidial-adapter:8095/readyz` | Core adapter worker readiness; this is not proof of remote Asterisk, calls, or VICIdial database health |

Prometheus alerts after two minutes of failed HTTP probing, failed exporter scraping,
or a missing expected target. Application, service, and production labels identify
the affected service for Alertmanager routing. Do not infer success from
`up{job="blackbox_platform_services"}` alone; require `probe_success == 1` too.

When a probe fails, first verify Blackbox is attached to the accepted monitoring,
backend, and edge networks. The 2026-09-10 incident demonstrated that a correct
Compose file can coexist with an old container attached only to monitoring.
Check the configured URL from the exporter network, then check the application's
readiness response. Preserve genuine dependency failures.

Before applying, validate the exact accepted source with promtool, preserve the
current effective configuration and rules, and use a controlled Prometheus reload.
Keep all unrelated runtime configuration, secret mounts, retention, networks, and
images. Verify all four targets and rule groups are present after at least two
scrape intervals. Roll back only this job and its rule file if verification fails.

Remote VICIdial telemetry requires its approved private authenticated connection.
Do not give the exporter a remote operational-write credential or open MariaDB.
Provider-host Grafana, Loki, Tempo, and collectors require their own accepted
release and connection evidence before this local coverage becomes a central
provider dashboard integration.
