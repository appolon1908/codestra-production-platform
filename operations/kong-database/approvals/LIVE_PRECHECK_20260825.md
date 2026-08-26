# Kong database live precheck — 2026-08-25

Change: `CHG-20260826-KONG-DB-HA-01`

Captured read-only at `2026-08-25T22:21:56-04:00`. No production state was
mutated. Secret values and database contents are excluded.

## Passing evidence

| Gate | Result |
| --- | --- |
| Kong gateway and PostgreSQL containers | PASS, healthy |
| Public PostgreSQL ports | PASS, zero |
| Primary host disk | PASS, 79% used |
| Kong topology | PASS, 19 services / 27 routes / 115 plugins |
| Backup timer | PASS; latest unit execution exited successfully |
| Replica candidate capacity | PASS, 20 CPU / ~62.6 GiB RAM / ~363 GiB free |
| Replica failure domain | PASS, separate bare-metal host |
| Replica-to-primary private SSH path | PASS |
| Public stable-name records | PASS, no public A or AAAA response |

## Gates not yet deployed

| Gate | Observed result |
| --- | --- |
| PostgreSQL minor version | FAIL, 17.6; target 17.11 |
| PostgreSQL TLS | FAIL, off |
| WAL archiving | FAIL, `archive_mode=off` |
| Runtime role separation | FAIL, `kong_runtime` absent |
| Legacy runtime privilege | FAIL, `kong` retains all elevated attributes |
| Streaming replication and active slot | FAIL, zero |
| Replica PostgreSQL | FAIL, not installed or listening |
| Replica-to-primary PostgreSQL path | FAIL, closed or filtered |
| Stable private DNS | FAIL, not resolvable |
| Protected DB secret authority | FAIL, expected directory absent |
| Restricted telephony safety action | FAIL, non-interactive sudo denied |
| Active calls/channels | UNKNOWN pending authoritative sanitized readback |
| Approved cutover window | NOT STARTED; begins 2026-08-28T00:00:00-04:00 |

```text
KONG_DB_CHANGE_PRECHECK=FAIL
KONG_DB_CUTOVER_GO=NO
```

The protected validator must be rerun inside the approved window with fresh
backup, off-host, restore, PITR, rollback, and telephony evidence. Any remaining
failed or unknown gate prohibits database mutation.
