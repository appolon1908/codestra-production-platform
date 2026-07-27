# Application Server A Baseline

Verified UTC: 2026-07-27T21:33Z.

## Identity

- Role: Application Server A
- Address: `65.109.65.169`
- VICIdial peer: `65.21.67.207`
- Repository branch: `release/production-activation`
- Current and published head: `6fa326d`
- Protected environment mode: `0600`
- Working tree: dirty before this work; existing untracked and modified artifacts
  were preserved.

## Runtime inventory

Docker 29.6.2 and Compose 5.3.1 are active. The runtime includes healthy
production containers for Odoo 19, middleware, PostgreSQL, Redis, n8n,
Keycloak, and the reverse proxy.
Separate staging Odoo, middleware, n8n, PostgreSQL, Redis, callback, and worker
containers are also present. The middleware control-plane roles include the
integration API, event gateway, policy engine, provisioning, reconciliation,
notification, scheduler, sync, evidence, allocation, PJSIP, VICIdial-adapter
client, and webphone-session services. Monitoring includes Prometheus,
Alertmanager, Blackbox Exporter, cAdvisor, Node Exporter, and a receiver.

Caddy runs in the `codestra-reverse-proxy-1` container and owns public ports 80
and 443. SSH is the only other public TCP listener. PostgreSQL and Redis expose
container-network ports only. UFW defaults to deny incoming and permits only
22, 80, and 443.

## Public health

| Service | Endpoint | Result |
|---|---|---|
| Odoo | `https://crm.codestra.agency/web/health` | HTTP 200 |
| Middleware | `https://api.codestra.agency/healthz` | HTTP 200 |
| n8n | `https://n8n.codestra.agency/healthz` | HTTP 200 |
| Keycloak | `https://auth.codestra.agency/` | HTTP 200 |

The CRM, API, and n8n certificates expire 2026-10-18. The Keycloak certificate
expires 2026-07-28 and requires immediate renewal verification.

## VICIdial reachability

- SSH port 22: reachable.
- HTTPS port 443: reachable, but the required adapter paths return HTTP 404.
- Adapter port 9443: unreachable.
- Remote database access was not opened or tested.

## Tests

The pre-change `pytest -q` run passed 78 tests and 9 subtests in 1.97 seconds.
After the first campaign-design implementation slice, it passed 94 tests and 9
subtests in 2.59 seconds. Python bytecode compilation and `git diff --check`
also pass.

## Backup and rollback

Local database/filestore backups, checksum files, a 2026-07-25 database and
filestore restore proof, and 2026-07-26/27 rollback rehearsals exist. The
repository's backup timer units are not installed under their expected names;
all queried backup timers were inactive. Current exact-release restore proof
therefore remains a production gate.

## Safety state

Production activation is not authorized. Restricted VICIdial adapter
reachability, backup scheduling/current restore proof, and the near-expiry
Keycloak certificate remain blocked or partial. Existing unclassified
working-tree artifacts remain preserved and unstaged. No firewall, remote
database, live dialing, or production feature flag was changed.
