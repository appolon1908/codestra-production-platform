# Network Port Matrix

| Address/port | Purpose | Required exposure | Evidence | Result |
|---|---|---|---|---|
| current host `:22` | SSH | public controlled | listening | PASS/needs upstream source policy review |
| current host `:80/:443` | Caddy ingress | public | Docker-published | PASS |
| current host `10.40.0.3:8443` | private Caddy ingress | vSwitch only | bound specifically to private IP | PASS exposure |
| middleware `10.40.0.1:8095` | control-plane HTTP | vSwitch only | `/health` HTTP 200 | PASS |
| `5432` | PostgreSQL | private/container only | no host listener; containers unpublised | PASS |
| `6379` | Redis | private/container only | no host listener; containers unpublised | PASS |
| `4222/6222/8222` | NATS | private/container only | no published host ports | PASS exposure; runtime audit BLOCKED |
| `5672/15672` | RabbitMQ | private only | no listener/service discovered | N/A |
| `3306` | VICIdial MariaDB | local to VICIdial only | no listener here | PASS boundary |
| crawler browser/debug | internal only | never public | none discovered | PASS exposure |

VSwitch fact: VLAN 4001, MTU 1400, current host `.3`; `.1` reachable, `.2` unreachable. This conflicts with the mission topology and is not automatically repairable without risking unrelated infrastructure.
