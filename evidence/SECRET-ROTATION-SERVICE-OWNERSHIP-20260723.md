# Secret rotation service ownership remediation

Evidence date: `2026-07-23`

```text
SCRIPT_COMMIT=ee725cd
OWNERSHIP_MANIFEST_SHA256=5b0043d73892e3852aa4b304c11a26e37dd5ad4852fa108d2011cd2e8411b883
SECRET_ROTATION_SERVICE_OWNERSHIP_GATE=FAIL
SECRET_VALUES_RECORDED=false
```

## Inventory and current rollback state

The authoritative metadata below was captured on the host with
`stat -c '%u:%g %a' <secret-path>`. Container-visible metadata was separately
checked with the same numeric format. All mounts resolved to their expected
host and container paths and were read-only.

| Service | Secret | Host path | Container path | Before UID:GID mode | Current UID:GID mode | Read-only | Health check | Current health |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PostgreSQL | `postgres_superuser_password` | `/etc/codestra/secrets/codestra-compose/postgres_superuser_password` | `/run/secrets/postgres_superuser_password` | `0:0 400` | `0:0 400` | yes | container health status | healthy |
| Redis | `redis_password` | `/etc/codestra/secrets/codestra-compose/redis_password` | `/run/secrets/redis_password` | `999:1000 400` | `999:1000 400` | yes | authenticated Redis health check | healthy |
| Redis | `redis_users_acl` | `/etc/codestra/secrets/codestra-compose/redis_users_acl` | `/run/secrets/redis_users_acl` | `999:1000 400` | `999:1000 400` | yes | authenticated Redis health check | healthy |
| Odoo | `odoo_db_password` | `/etc/codestra/secrets/codestra-compose/odoo_db_password` | `/run/secrets/odoo_db_password` | `100:101 400` | `100:101 400` | yes | `GET /web/health` inside container | healthy |
| n8n | `n8n_db_password` | `/etc/codestra/secrets/codestra-compose/n8n_db_password` | `/run/secrets/n8n_db_password` | `1000:1000 400` | `1000:1000 400` | yes | `GET /healthz` inside container | healthy |
| Middleware | `database_url` | `/etc/codestra/secrets/codestra-compose/database_url` | `/run/secrets/database_url` | `10001:999 400` | `10001:999 400` | yes | `GET /healthz` inside container | healthy |
| Middleware | `redis_url` | `/etc/codestra/secrets/codestra-compose/redis_url` | `/run/secrets/redis_url` | `10001:999 400` | `10001:999 400` | yes | `GET /healthz` inside container | healthy |

“Current” is the recovered rollback state, not proof of a successful new
rotation. No credential was changed during this remediation run.

## Implementation

The version-controlled TSV manifest records only identifiers, paths, numeric
UID:GID, mode, read-only status, and validation commands. It contains no secret
values.

The replacement tool:

- requires numeric UID and GID and rejects missing values or unexpected
  `65534:65534`;
- rejects destinations that are directories, symlinks, absent, or outside the
  approved root;
- captures existing metadata using `stat -c '%u:%g %a'`;
- rejects group/world access and modes broader than the manifest;
- creates the temporary file beside the destination, writes without logging,
  flushes and `fsync`s it, applies numeric ownership and mode, verifies it is
  non-empty, renames it atomically, and `fsync`s the directory;
- validates the container read path, health, new-credential acceptance, and
  old-credential rejection while discarding validator stdout and stderr;
- operates on exactly one named consumer per invocation; and
- restores the original bytes and metadata atomically and restarts the same
  consumer if any replacement or validation step fails.

## Regression results

```text
STANDARD_LIBRARY_TESTS=10
STANDARD_LIBRARY_TESTS_RESULT=PASS
ATOMIC_REPLACEMENT=PASS
NUMERIC_OWNERSHIP_AND_MODE=PASS
FIVE_DISTINCT_SERVICE_OWNERS=PASS
MISSING_UID_OR_GID_REJECTION=PASS
NOBODY_NOGROUP_REJECTION=PASS
DIRECTORY_AND_SYMLINK_REJECTION=PASS
BROADER_MODE_REJECTION=PASS
INJECTED_CHOWN_FAILURE=PASS
FAILED_HEALTH_CHECK_ROLLBACK=PASS
OLD_CREDENTIAL_STILL_VALID_ROLLBACK=PASS
ROLLBACK_TEST=PASS
STDOUT_STDERR_EVIDENCE_SECRET_LEAK_TEST=PASS
```

The regression suite used synthetic values only. Neither synthetic nor runtime
secret values appear in stdout, stderr, the ownership manifest, or this
evidence.

## Runtime acceptance and gate decision

```text
POSTGRES_HEALTH=PASS
REDIS_HEALTH=PASS
ODOO_HEALTH=PASS
N8N_HEALTH=PASS
MIDDLEWARE_HEALTH=PASS
NEW_CREDENTIAL_ACCEPTANCE=NOT_RUN
OLD_CREDENTIAL_REJECTION=NOT_RUN
STAGING_ROTATION_1=NOT_RUN
STAGING_ROTATION_2=NOT_RUN
RUNTIME_ROLLBACK_PROOF=PRIOR_ROLLBACK_ONLY
SECRET_SCAN=TESTED_OUTPUT_PATHS_ONLY
```

The approved credential-validation executable referenced by the manifest is
not installed at `/opt/codestra/bin/validate-rotated-credential`, and no
separate five-service staging stack or staging credential set was identified.
The tool therefore cannot complete a live rotation and will fail closed if
validation is attempted. Production credentials were not rotated to substitute
for missing staging prerequisites.

`SECRET_ROTATION_SERVICE_OWNERSHIP_GATE` remains `FAIL`. It may be changed to
`PASS` only after an approved staging validator is installed, all five
consumers complete two consecutive one-at-a-time staging rotations, every new
credential is accepted, every old credential is rejected after the rotation
window, rollback is demonstrated in that environment, and a repository and
evidence secret scan passes.

Fail-closed controls were preserved: no live VICIdial calls, production n8n
workflow activation, outbound email/carrier event, production database
migration, or production credential rotation was performed.
