# Network and Port Matrix

VLAN 4001 is up on `enp41s0.4001`, `10.40.0.1/24`, MTU 1400. Klyrow uses the conflict-free `10.40.0.4`; the legacy `.2` address remains assigned to VICIdial. Peer ICMP is blocked; private TCP 22 and 8443 succeed.

| Port | Purpose / scope | Evidence | Result |
|---|---|---|---|
| 22 | public SSH | live connection | PASS |
| 80/443 | intended public ingress | DNS matches; host refuses TCP | FAIL: ingress proxy not published |
| 443 on `10.40.0.1` | peer-only middleware mTLS | private bind; client certificate required | PASS |
| 8095 on `10.40.0.1` | Klyrow gateway from `10.40.0.4` | exact-source UFW; local and peer health 50/50; `.2` removed from the allowance because it is owned by VICIdial | PASS |

Postal `MessageHeld` callbacks are normalized from `klyrow.email.held` to the
supported `klyrow.email.deferred` delivery state while retaining the provider
event type in the payload. Callback `453bc7af-4367-454c-b80f-5ac01eea9b18`
was re-driven without SMTP activity and completed through n8n execution `120`
to Odoo delivery-status record `5` with correlation preserved and no duplicate
Odoo record.
| 8096 | loopback/Docker control plane | loopback bind; live health | PASS |
| 8443 on `10.40.0.2` | remote adapter | mTLS health/readiness 200 | PASS |
| 4222/8222 | NATS/monitoring loopback | loopback listeners | PASS |
| 5432/6379 | PostgreSQL/Redis Docker-private | no host/public listener | PASS |
| 5678/8069 | n8n/Odoo Docker-private | live health; no host/public listener | PASS |

Public probes confirmed internal application/data ports are not exposed. Docker socket is not TCP-exposed. Remote VICIdial telephony ports are outside this matrix; its MariaDB is loopback-only.
