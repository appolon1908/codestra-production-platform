# Shared PostgreSQL PITR activation and rollback

1. Run `validate-change-authority.sh` with the protected approved-change file.
   Stop without mutation unless it prints `SHARED_POSTGRES_CUTOVER_GO=YES`.
2. Capture database/consumer inventory, PostgreSQL settings, image digest, and
   restart counts. Require fresh encrypted logical/off-host backup and restore.
3. Install the archive script and protected authority files. Validate paths,
   modes, GPG recipient, restic repository, capacity, and remote write/readback.
4. Install `postgresql-pitr.conf`; capture the previous effective configuration.
5. Restart PostgreSQL once inside the approved window. Validate every database
   and application consumer before continuing.
6. Force a WAL switch, require `archive_mode=on`, zero new archive failures,
   encrypted remote WAL, and matching local/remote SHA-256.
7. Run `create-base-backup.sh`, retrieve it from the independent authority, and
   verify its checksum and decryption in an isolated internal-only network.
8. Create pre/post markers around a recorded recovery target, archive actual WAL,
   recover into isolated PostgreSQL with `restore_command`, and prove the pre
   marker exists while the post marker does not. Verify every shared database and
   application-role connection. Publish only sanitized evidence.
9. Only after PITR PASS may the middleware release enter write freeze.

Rollback: if PostgreSQL, archiving, or any consumer fails, restore the captured
configuration and restart only within the approved window. Revalidate all
consumers. Do not migrate middleware. Preserve failed archive evidence without
secrets. Never restore over production and never create another writable primary.
