# API Connectivity Inventory

| Service | Direction | Protocol / address | Auth | TLS/mTLS | Owner | Health | Status |
|---|---|---|---|---|---|---|---|
| Control plane | inbound | HTTP, repo default `127.0.0.1:8096`; live `10.40.0.1:8095` | operator bearer or service bearer + HMAC | private ingress intended | `control_plane_service` | `/health`, `/ready`, `/metrics` | health PASS; runtime inspection BLOCKED |
| Odoo | both | configured HTTP service URL | service identity; event HMAC inbound | deployment-defined | worker / Odoo adapter | not discovered | BLOCKED |
| n8n | both | configured HTTP webhook URL | service identity; event HMAC inbound | deployment-defined | worker / n8n | not discovered | BLOCKED |
| Telnexa/Jasmin | both | simulator locally; production restricted to private `10.40.0.2` | outbound bearer; inbound bearer + HMAC | ordinary TLS planned | provider adapter | readiness exposes mode | simulator PASS; production BLOCKED |
| Klyrow/Mautic/Postal | both | test locally; production restricted to private `10.40.0.2` | outbound bearer; inbound bearer + HMAC | ordinary TLS planned | provider adapter | readiness exposes mode | test PASS; production BLOCKED |
| Kyqra/Crawlee | both | test job API; production restricted to private `10.40.0.2` | outbound bearer; inbound bearer + HMAC | ordinary TLS planned | provider adapter | no dedicated health | safe test PASS; production BLOCKED |
| SQLite ledger | internal | `/data/control-plane.db`, WAL | filesystem identity | N/A | API + worker | exercised by `/ready` | PASS locally |
| NATS JetStream | internal | URL supplied by secret file/environment | NATS credentials + CA/client cert refs | mTLS contract | eventing workers | 8222 where deployed | BLOCKED live; contract PASS |
| Redis | internal | discovered only as unexposed Docker dependencies on current host | deployment secret | private | unrelated/current apps | container health | exposure PASS; middleware use not present |
| PostgreSQL | internal | unexposed Docker networks on current host | deployment secret | private | application stacks | container health | exposure PASS; Odoo absent |

Repository configuration sources: `config/control-plane.env.example`, `deploy/control-plane/compose.yaml`, `control_plane_service/server.py`, `control_plane_service/worker.py`, `control_plane_service/providers.py`, `eventing/jetstream_contract.json`, and `docs/openapi/control-plane-v1.yaml`.

Live host inventory: public `49.12.145.107`, VLAN 4001 `10.40.0.3/24`, MTU 1400; public listeners 22/80/443; private-only 8443; loopback-only application/monitoring/database verification ports. This is not the declared middleware host.
