# Server A production certification — 2026-09-01

Server A is certified GO / PRODUCTION-READY after live remediation and independent backup/restore verification.

Passed gates:

- isolated Kong restore: 20 services, 29 routes, 125 plugins, 9-second RTO, zero public ports;
- Kong memory below 50% of a bounded 3 GiB limit;
- filesystem usage below the 75% warning threshold with seven verified backup generations retained;
- zero failed systemd units, restarting containers, unhealthy production containers, or down Prometheus targets;
- zero firing warning, high, or critical alerts;
- dedicated internal Prometheus-to-Alertmanager transport verified ready;
- encrypted backup `/opt/codestra/backups/production-readiness-local/20260901T111246Z` verified;
- isolated restore `/opt/codestra/evidence/production-readiness-restore/20260901T111644Z` verified;
- WebSocket PostgreSQL streaming replica in recovery with zero-byte lag.

Host evidence is stored at `/opt/codestra/evidence/production-certification-20260901T112100Z`.
