# External monitoring input form

Do not commit completed values. Store approved records only in protected administrative systems.

| Required external input | Protected reference/value location | Validation owner | Status |
|---|---|---|---|
| Production primary receiver | `/etc/codestra/secrets/monitoring/primary_receiver_url` | unassigned | BLOCKED |
| Production secondary receiver | `/etc/codestra/secrets/monitoring/secondary_receiver_url` | unassigned | BLOCKED |
| Recovery receiver | `/etc/codestra/secrets/monitoring/recovery_receiver_url` | unassigned | BLOCKED |
| Rejected-route audit receiver | `/etc/codestra/secrets/monitoring/rejected_route_url` | unassigned | BLOCKED |
| Primary escalation owner record | governance reference | unassigned | BLOCKED |
| Secondary escalation owner record | governance reference | unassigned | BLOCKED |
| Primary acknowledgment window | governance reference | unassigned | BLOCKED |
| Secondary escalation window | governance reference | unassigned | BLOCKED |
| Escalation policy | governance reference | unassigned | BLOCKED |
| Monitoring approval/change window | governance reference | unassigned | BLOCKED |

Receiver files must be nonempty approved HTTP(S) endpoints with protected permissions. Placeholder, `.invalid`, example, localhost, and inline destinations are rejected. Personal contacts and receiver secrets must never enter Git.
