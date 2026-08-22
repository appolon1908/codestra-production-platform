# API Connectivity Inventory

Audit time: 2026-08-15 UTC. Evidence: `artifacts/connectivity-audit.json`. This inventory describes observed runtime, not only repository intent. Secret values were never printed. `PASS` means a live request or protocol exchange succeeded.

| Service | Direction | Protocol / address | Auth and TLS | Health | Live status |
|---|---|---|---|---|---|
| Integration control plane | internal clients -> middleware | HTTP, `127.0.0.1:8096`, Docker edge | bearer + HMAC on ingress; operator bearer | `/health`, `/ready`, `/v1/ready`, `/metrics` | PASS: 51 safe live tests |
| Private integration gateway | shared host -> middleware | HTTP, `10.40.0.1:8095` | per-service bearer + HMAC + timestamp | service health and metrics | PASS: 42 safe live tests |
| Private mTLS ingress | VICIdial/shared host -> middleware | HTTPS, `10.40.0.1:443` | required client certificate; private CA | private routes | PASS configuration/certificate; peer callback not safely initiated locally |
| Odoo 19 | middleware <-> Odoo | Docker `codestra-odoo-1:8069` | intended application API; no control-plane credential deployed | `/web/health` | network PASS; functional BLOCKED |
| n8n | middleware <-> n8n | Docker `codestra-n8n-1:5678` | intended credential/HMAC; absent in production n8n env | `/healthz` | network PASS; functional BLOCKED |
| Telnexa SMS | middleware -> simulator; callbacks -> middleware | local simulator; callbacks on 8095/control plane | bearer + HMAC callback | provider status route | PASS in simulator; no carrier submission |
| Klyrow email | middleware -> test adapter; callbacks -> middleware | local test mode; callbacks on 8095/control plane | bearer + HMAC callback | Klyrow health on 8095 | PASS in test mode; no delivery attempted |
| Kyqra crawler | middleware <- results/events | private callbacks on 8095/control plane | bearer + HMAC | Kyqra health on 8095 | inbound PASS; outbound job API FAIL |
| VICIdial restricted adapter | middleware -> shared host | mTLS `10.40.0.2:8443` | private CA; HMAC for mutations | `/health`, `/ready` | PASS health/readiness and missing-client rejection |
| NATS JetStream | local publishers/consumers | `127.0.0.1:4222`; monitor 8222 | loopback-only | monitor port | PASS listener; isolated retry/DLQ tests PASS |
| Redis | middleware/n8n queues | Docker-only 6379 | ACL secret files | container health | PASS; public exposure blocked |
| PostgreSQL | Odoo/n8n/middleware state | Docker-only 5432 | file-mounted roles | container/exporter health | PASS; public exposure blocked |
| Prometheus | monitoring | Docker-only 9090 | internal network | API | PASS: 28/28 targets UP |

Observed runtime also includes Keycloak, OAuth2 Proxy, provisioning, notification/reconciliation/scheduler/telephony workers, Alertmanager, blackbox exporter, node exporter, cAdvisor, database exporters, and backup containers. No RabbitMQ, Mautic, Postal, Jasmin, Crawlee, Playwright, or Kyqra worker was observed on this host. The `10.40.0.2` peer is currently the VICIdial host; it did not expose the named Klyrow/Telnexa/Kyqra deployment accounts.
