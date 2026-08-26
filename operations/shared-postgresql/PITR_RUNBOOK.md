# Shared PostgreSQL PITR activation and rollback

1. Run `validate-change-authority.sh` with the protected approved-change file.
   Stop without mutation unless it prints `SHARED_POSTGRES_CUTOVER_GO=YES`.
2. Capture database/consumer inventory, PostgreSQL settings, image digest, and
   restart counts. Require fresh encrypted logical/off-host backup and restore.
3. Record exactly one HA policy:
   - `REQUIRED`: provide fresh replica, streaming-replication, fencing, and stable
     private-authority evidence bound to the same change ID.
   - `FORMALLY_NOT_REQUIRED_FOR_THIS_RELEASE`: record rationale, accepted risk, a
     future review date, and a measured restore RTO that does not exceed the
     approved RTO. A contradictory restore result keeps the cutover closed.
4. Install the stage, archive, prune, restore, metrics, base-backup, and restic
   maintenance helpers. Provision the WAL stage as `root:postgres` `0770`.
   PostgreSQL receives only stage access. The root offload service alone receives
   the encryption public key and dedicated off-host credential. PostgreSQL
   receives no private decryption key, object-store credential, or unrelated
   secret.
5. Keep the authoritative backup passfile root-owned and mode `0600`. The
   base-backup helper creates a temporary `0600` copy owned by the exact
   PostgreSQL container UID/GID, proves that non-root identity can read it, mounts
   only the temporary copy, and securely removes it after the run.
6. Install `postgresql-pitr.conf`; capture the previous effective configuration.
7. Restart PostgreSQL once inside the approved window. Validate every database
   and application consumer before continuing.
8. Force a WAL switch, require `archive_mode=on`, zero new archive failures,
   encrypted remote WAL, and matching local/remote SHA-256.
9. Run `create-base-backup.sh`. It uses PostgreSQL 17 plain format with streamed
   WAL, requires and verifies `backup_manifest`, archives the completed directory,
   encrypts it, creates relocatable checksums, verifies the remote objects, and
   securely removes temporary plaintext. Retrieve it and verify it in isolation.
10. Create pre/post markers around a recorded recovery target, archive actual WAL,
    recover into isolated PostgreSQL with `restore_command`, and prove the pre
    marker exists while the post marker does not. Verify every shared database and
    application-role connection. Publish only sanitized evidence.
11. Enable `codestra-shared-postgres-restic-maintenance.timer`. The maintenance
    service shares the repository lock with WAL and base-backup publication,
    performs repository checks before and after pruning, applies WAL/base
    retention, publishes repository usage/capacity metrics, and fails closed on
    corruption or an invalid configured capacity.
12. Only after PITR PASS may the middleware release enter write freeze.

## Repository maintenance evidence

Before relying on the timer, run the service manually and require:

```text
restic check=PASS
restic forget=PASS
restic prune=PASS
post-prune restic check=PASS
maintenance last-success metric > 0
maintenance failures increase=0
repository capacity alert state=healthy or formally unavailable
```

Configure optional `/etc/codestra/secrets/shared-postgresql/restic-capacity-bytes`
when the repository authority publishes a hard quota. Without that value, usage is
still exported but percentage-based remote-capacity alerts remain intentionally
inactive. Local WAL/base-backup storage alerts remain mandatory.

## Rollback

If PostgreSQL, archiving, repository maintenance, or any consumer fails, restore
the captured configuration and restart only within the approved window. Revalidate
all consumers. Do not migrate middleware. Preserve failed archive evidence without
secrets. Never restore over production and never create another writable primary.

## Pre-installation executable rehearsals

Run both:

```text
bash tests/integration/shared_postgresql_base_backup_helper.sh
bash tests/integration/shared_postgresql_pitr_execution.sh
```

They expose no public port and use no production data or secrets. The first runs
the actual production base-backup helper with a root-only authority passfile and a
non-root PostgreSQL utility container. The second proves PostgreSQL 17 base backup,
manifest verification, encrypted-artifact relocation, `restore_command` WAL
recovery, and timestamp PITR with the pre-target marker present and the post-target
marker absent.
