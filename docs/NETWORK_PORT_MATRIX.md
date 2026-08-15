# Network and Port Matrix

VLAN 4001 is up on `enp41s0.4001`, `10.40.0.1/24`, MTU 1400. ARP for `10.40.0.2` is live. Peer ICMP is blocked; private TCP 22 and 8443 succeed.

| Port | Purpose / scope | Evidence | Result |
|---|---|---|---|
| 22 | public SSH | live connection | PASS |
| 80/443 | intended public ingress | DNS matches; host refuses TCP | FAIL: ingress proxy not published |
| 443 on `10.40.0.1` | peer-only middleware mTLS | private bind; client certificate required | PASS |
| 8095 on `10.40.0.1` | gateway from `10.40.0.2` | exact-source UFW; live health | PASS |
| 8096 | loopback/Docker control plane | loopback bind; live health | PASS |
| 8443 on `10.40.0.2` | remote adapter | mTLS health/readiness 200 | PASS |
| 4222/8222 | NATS/monitoring loopback | loopback listeners | PASS |
| 5432/6379 | PostgreSQL/Redis Docker-private | no host/public listener | PASS |
| 5678/8069 | n8n/Odoo Docker-private | live health; no host/public listener | PASS |

Public probes confirmed internal application/data ports are not exposed. Docker socket is not TCP-exposed. Remote VICIdial telephony ports are outside this matrix; its MariaDB is loopback-only.
