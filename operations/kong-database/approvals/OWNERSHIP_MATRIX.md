# Kong database change ownership matrix

Assignments below were accepted by accountable owner Ralph Appolon for
`CHG-20260826-KONG-DB-HA-01`.

| Role | Assignee | Responsibility / required approval | During change | Rollback responsibility | Escalation path |
| --- | --- | --- | --- | --- | --- |
| CHANGE_OWNER | Ralph Appolon | Own scope, window and final go/no-go | Chair checkpoints | Order stop/rollback | Change authority |
| DATABASE_OWNER | Ralph Appolon | Approve PostgreSQL, roles, HBA, TLS, PITR | Validate DB/LSN | Restore/promote DB safely | DBA incident lead |
| PLATFORM_OWNER | Ralph Appolon | Approve hosts, networks and deployment | Execute reviewed release | Restore platform config | Platform incident lead |
| ROLLBACK_OWNER | Ralph Appolon | Accept rollback criteria/artifacts | Track abort thresholds | Direct rollback | Change owner |
| CANARY_OWNER | Ralph Appolon | Approve harmless authenticated canary | Observe runtime evidence | Close bypass immediately | Application owner |
| FAILOVER_OWNER | Ralph Appolon | Approve promotion and rejoin | Control failover sequence | Select authoritative timeline | Database owner |
| FENCING_OWNER | Ralph Appolon | Own enforceable fence | Confirm old primary isolated | Authorize safe unfence | Infrastructure owner |
| DNS_OWNER | Ralph Appolon | Own private zone and TTL | Mutate only after promotion | Restore prior target | Network owner |
| SECRET_OWNER | Ralph Appolon | Approve backend/access | Release role references | Revoke compromised secrets | Security owner |
| ROTATION_OWNER | Ralph Appolon | Own rotation schedule | Record deployed versions | Restore rollback credential | Secret owner |
| TELEPHONY_OPERATOR_OWNER | Ralph Appolon | Certify zero activity safely | Run sanitized readback | Preserve maintenance gate | Telephony incident lead |
