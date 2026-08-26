# Maintenance window request

Requested decision: approve a database cutover window and separate failover and
load/soak windows. No clock time is approved by this document.

| Sequence | Estimate |
| --- | ---: |
| Freeze and fresh encrypted/off-host backup | 15 min |
| PostgreSQL 17.11 restart and validation | 15 min |
| Role deployment and Kong credential cutover | 20 min |
| HBA/TLS deployment and validation | 20 min |
| WAL activation and physical base backup | 30 min |
| Replica initialization and parity checks | 60 min |
| Stable authority and monitoring validation | 20 min |
| Rollback reserve | 60 min |

`MINIMUM_REQUIRED_WINDOW=180 minutes`

`RECOMMENDED_WINDOW=240 minutes`

`ROLLBACK_RESERVE=60 minutes`

`APPROVED_START=2026-08-28T00:00:00-04:00`

`APPROVED_END=2026-08-28T04:00:00-04:00`

`TIMEZONE=America/Santo_Domingo`

`FAILOVER_REHEARSAL_WINDOW=2026-08-29T00:00:00-04:00/2026-08-29T02:00:00-04:00`

`LOAD_SOAK_WINDOW=2026-08-30T00:00:00-04:00/2026-08-30T04:00:00-04:00`

The change owner stops before mutation if the approval validator fails. Abort
criteria include stale backup, restore failure, topology mismatch, HBA/TLS
failure, datastore failure, replication outside RPO, or unavailable rollback.
