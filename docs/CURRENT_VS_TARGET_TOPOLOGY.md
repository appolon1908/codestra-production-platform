# Current versus target topology

| Capability | Current transitional runtime | SPEC-1 target | Status |
|---|---|---|---|
| Public edge | Reverse proxy consolidated on Server A | Two DMZ edge/WAF/LB nodes in `10.10/24` | TARGET_PHASE_2 |
| Odoo app | Consolidated Server A | Two app nodes in `10.20/24` | TARGET_PHASE_2 |
| Odoo DB | PostgreSQL on Server A | HA/managed PostgreSQL in `10.30/24` | TARGET_PHASE_2 |
| Odoo filestore | Local Docker volume with paired restore evidence | Shared HA object/file strategy | BLOCKED |
| Middleware API/workers | Consolidated Server A | Separate redundant API and worker nodes | TARGET_PHASE_2 |
| Control PostgreSQL | Consolidated Server A | Three nodes in `10.30/24` | TARGET_PHASE_2 |
| Redis/NATS | Consolidated Server A | Three-node HA services in `10.30/24` | TARGET_PHASE_2 |
| Keycloak/n8n | Consolidated Server A | Redundant application-zone nodes | TARGET_PHASE_2 |
| VICIdial/Asterisk | Server B `10.40.0.2` | Redundant web/dialer/database tiers | TARGET_PHASE_2 |
| Restricted adapter | Private Server B listeners; port migration pending | Adapter pair behind `10.40.0.2:8443` VIP | BLOCKED |
| AI voice | Disabled | Redundant AI edge/gateway in `10.50/24` | TARGET_PHASE_2 |
| Observability | Consolidated monitoring | Redundant `10.60/24` observability | TARGET_PHASE_2 |
| Release supply chain | PR CI only before this rebaseline | Exact-SHA signed immutable release | IMPLEMENTED |
| Backups | Encrypted backups and isolated DB/filestore restore evidence | Cross-zone/off-site DR with measured RPO/RTO | TESTED |

The current `10.40.0.1` placement of Server A is a known transitional exception;
no readdressing is authorized by this rebaseline.
