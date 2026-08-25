# 16 — Observability

Scope: codestra-app host monitoring stack (`codestra-monitoring-*` Compose project). Evidence via `docker ps`, `docker inspect`, `docker logs`.

## Stack inventory

| Component | Container | Status at audit time |
|---|---|---|
| Metrics DB / scraper | `codestra-monitoring-prometheus-1` | **`Exited (0)`, 22 min before audit** — see Finding below |
| Alert routing | `codestra-monitoring-alertmanager-1` | Up |
| Host metrics | `codestra-monitoring-node-exporter-1` | Up |
| Container metrics | `codestra-monitoring-cadvisor-1` | Up (healthy) |
| Blackbox probing | `codestra-monitoring-blackbox-1` | Up |
| Postgres metrics | `codestra-reviewed-monitoring-postgres-exporter-1` | Up |
| Redis metrics | `codestra-reviewed-monitoring-redis-exporter-1` | Up |
| Custom receiver | `codestra-monitoring-receiver-receiver-1` | Up (healthy) |
| Dashboards (Grafana) | **not found** — no `grafana` container or config located anywhere under `/opt/codestra` | absent |

**Finding OBS-P1-01 — The metrics database (Prometheus) is down while every exporter and Alertmanager remain up, i.e. the entire monitoring stack is currently blind.**
- Observed evidence: `docker ps -a --filter name=codestra-monitoring` shows `codestra-monitoring-prometheus-1` as `Exited (0) 22 minutes ago` at audit time, while its 5 sibling monitoring containers are `Up`. `docker inspect` shows `RestartPolicy=unless-stopped`, `ExitCode=0`, and the container's own log tail shows a **graceful shutdown via SIGTERM** (`msg="Received an OS signal, exiting gracefully..." signal=terminated`) at `2026-08-25T12:18:37Z`, i.e. it was deliberately stopped (`docker stop`/compose stop), not crashed — yet a `RestartPolicy=unless-stopped` container that was stopped via `docker stop` will *not* auto-restart (this is expected Docker behavior for that policy, not a bug — but it means whoever/whatever stopped it left the stack without metrics and nothing brought it back).
- Expected state (mission Step 20): centralized metrics, API latency, queue depth, cert expiry, DB availability, auth failures, etc. all visible.
- Current state: **zero metrics have been collected since Prometheus stopped.** Alertmanager (still up) has nothing feeding it — any alert rules that depend on Prometheus evaluation are silently not firing, and this is itself invisible (no meta-monitoring/dead-man's-switch alert observed to catch "Prometheus is down").
- Risk: **P1** — a production incident occurring right now would have no metrics trail, and any Alertmanager-based paging for that incident would not fire. This directly undermines the mission's Step 20 requirement and any claim of "we'd know if it broke."
- Recommended fix: restart Prometheus (`docker start codestra-monitoring-prometheus-1` or via its compose project) **after Phase 1 human authorization** (this audit is read-only); more importantly, add a meta-monitoring check (e.g. blackbox probe of Prometheus's own `/-/healthy`, or an external heartbeat) so this specific failure mode — the monitoring system itself going dark — is not silent next time.
- Test required: after restart, confirm scrape targets return to "up" state and Alertmanager shows active routes again.
- Rollback: N/A, no changes made in Phase 1.
- GitHub repo: wherever `codestra-monitoring` compose/config is tracked (confirm in `03_GITHUB_RUNTIME_RECONCILIATION.md`). Suggested branch: `ops/restore-prometheus-and-add-meta-monitoring`.

**Finding OBS-P2-01 — No Grafana or equivalent dashboard layer found.**
- Observed evidence: no `grafana` container in `docker ps -a`; no grafana config directory found under `/opt/codestra`.
- Expected state: mission Step 20 explicitly lists "Grafana dashboards if present" — data exists (cadvisor, node-exporter, postgres/redis exporters) but there's no visualization layer, meaning anyone investigating an issue must query Prometheus's own UI/API directly (and could not do so anyway right now per OBS-P1-01) or use `codestra-monitoring-receiver-receiver-1` (purpose unconfirmed — worth a follow-up read of its config/image to see if it substitutes for a dashboard).
- Risk: P2 — raw metrics without dashboards raises the bar for anyone (human or on-call) to actually use the data during an incident.
- Recommended fix: stand up Grafana (or confirm the "receiver" container already serves this purpose and document it) with at least basic dashboards for the golden signals per service family (Odoo, middleware, Kong, n8n, email/SMS).
- Test required: N/A (net-new capability).
- Repo: monitoring compose repo. Suggested branch: `feature/add-grafana-dashboards`.

## Coverage gaps against the mission's Step 20 checklist

| Required signal | Status |
|---|---|
| Centralized/structured logs, correlation IDs | Not evaluated here — see `07_MIDDLEWARE.md` for whether the app emits correlation IDs; no centralized log aggregator (e.g. Loki/ELK) container found on this host, meaning `docker logs` per-container is the only access path |
| Prometheus metrics | Present in principle, **currently not running** (OBS-P1-01) |
| Grafana dashboards | **Absent** (OBS-P2-01) |
| Alerts | Alertmanager running but unverified whether it has real routes/receivers configured beyond defaults (needs config file review — not completed in this pass, flag as UNVERIFIED) and currently has no data source (OBS-P1-01) |
| Telephony metrics | UNVERIFIED from this host — cross-reference `06_VICIDIAL_ASTERISK.md` |
| API latency | cadvisor gives container-level CPU/mem, not application-level latency; no APM tool found — UNVERIFIED whether middleware emits its own latency metrics (check `07_MIDDLEWARE.md`) |
| Queue depth (NATS/Redis) | No NATS or Redis exporter found in the monitoring stack list (only postgres-exporter and redis-exporter are named, and redis-exporter IS present — but NATS has no exporter). **NATS queue depth is not monitored.** |
| Failed deliveries (email/SMS) | UNVERIFIED from this host — check `11_EMAIL.md`/`12_SMS.md` for whether these emit their own metrics/alerts |
| WebSocket connections | UNVERIFIED — no evidence of a metric for active WS connections found at this layer |
| Agent state | UNVERIFIED — cross-reference `05_AGENT_DESKTOP_AND_WEBRTC.md` |
| Certificate expiration | **Covered** — `codestra-cert-monitor.timer` and `public-tls-monitor.timer` both active and firing on schedule (per `01_RUNTIME_INVENTORY.md`) |
| Disk usage | node-exporter covers this in principle, but again unreadable while Prometheus is down; root disk already at 84% (see `01_RUNTIME_INVENTORY.md` INV-P2-01) with no confirmed alert threshold |
| Database availability | postgres-exporter present; same Prometheus-down caveat |
| Auth failures | UNVERIFIED — needs Keycloak/Kong log review, see `10_IDENTITY.md`/`08_KONG.md` |

**Finding OBS-P3-01** — No NATS-specific Prometheus exporter identified despite NATS being a running message bus on this host (per `01_RUNTIME_INVENTORY.md`). If middleware workers depend on NATS for event delivery, queue depth / consumer lag on that bus is currently invisible even when Prometheus is running.
- Recommended fix: add `natsio/prometheus-nats-exporter` (or enable NATS's built-in Prometheus endpoint) to the monitoring stack.
- Repo: monitoring compose repo. Suggested branch: `feature/nats-prometheus-exporter`.

## Summary counts for this file

P0: 0 · P1: 1 · P2: 1 · P3: 1
