# Application Server A Baseline

Generated UTC: 2026-07-27.

## Identity

- Role: Application Server A
- Address: `65.109.65.169`
- VICIdial peer: `65.21.67.207`
- Repository branch: `release/production-activation`
- Published head: `25cb2c90e2bed47929be32cf100889db74a90137`
- Protected environment mode: `0600`

## Runtime inventory

Docker is active. The runtime includes healthy production containers for Odoo
19, middleware, PostgreSQL, Redis, n8n, Keycloak, and the reverse proxy.
Separate staging Odoo, middleware, n8n, PostgreSQL, Redis, callback, and worker
containers are also present. Monitoring includes Prometheus, Alertmanager,
Blackbox Exporter, cAdvisor, Node Exporter, and a receiver service.

Caddy runs in the `codestra-reverse-proxy-1` container and owns public ports 80
and 443. The host-level Caddy service is inactive by design.

## Public health

| Service | Endpoint | Result |
|---|---|---|
| Odoo | `https://crm.codestra.agency/web/health` | HTTP 200 |
| Middleware | `https://api.codestra.agency/healthz` | HTTP 200 |
| n8n | `https://n8n.codestra.agency/healthz` | HTTP 200 |
| Keycloak | `https://auth.codestra.agency/` | DNS unresolved |

## VICIdial reachability

- SSH port 22: reachable.
- Adapter port 9443: unreachable.
- Remote database access was not opened or tested.

## Tests

`pytest -q` passes 78 tests and 9 subtests.

## Safety state

Production activation is not authorized. Public Keycloak DNS and VICIdial
adapter reachability remain blocked. Existing unclassified working-tree
artifacts are preserved and unstaged.
