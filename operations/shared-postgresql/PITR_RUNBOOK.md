# Shared PostgreSQL PITR activation and rollback

1. Run `validate-change-authority.sh` with the protected approved-change file.
   Stop without mutation unless it prints `SHARED_POSTGRES_CUTOVER_GO=YES`.
2. Capture database/consumer inventory, PostgreSQL settings, image digest, and
   restart counts. Require fresh encrypted logical/off-host backup and restore.
3. Install the stage, archive, prune, restore, metrics, and base-backup helpers.
   Provision the stage as `root:postgres` `0770`. PostgreSQL receives only stage
   access; the root offload service alone receives the encryption public key and
   dedicated off-host credential. PostgreSQL receives no private decryption key,
   off-host credential, or unrelated secret. For an SFTP restic authority, place
   the restricted SSH configuration and key below the protected
   `shared-postgresql/ssh-home` directory and install
   `codestra-shared-backup.ssh.conf` under `/etc/ssh/ssh_config.d`; the system
   client fragment is non-secret and `ProtectHome=true` remains enforced.
   Validate modes, forced-command restrictions, and remote readback.
4. Install `postgresql-pitr.conf`; capture the previous effective configuration.
   Render `compose.pitr-activation.yaml` together with the authoritative live
   Compose file and require semantic drift to be limited to the PostgreSQL
   command and the stage-helper/spool mounts. The helper must be read-only in
   the container; only the WAL spool is writable. Never activate the settings
   without this layer because the host helper is otherwise absent in the
   PostgreSQL mount namespace.
5. Restart PostgreSQL once inside the approved window. Validate every database
   and application consumer before continuing.
6. Force a WAL switch, require `archive_mode=on`, zero new archive failures,
   encrypted remote WAL, and matching local/remote SHA-256.
7. Before the physical backup, run `install-backup-hba.sh` with the exact
   PostgreSQL container, dedicated backup role, and private Docker-network CIDR.
   It atomically adds one role-specific `replication`/SCRAM rule and reloads
   PostgreSQL. Do not add a generic replication rule and do not use a public
   CIDR.
8. Run `create-base-backup.sh`. It uses PostgreSQL 17 tar format with fetched WAL
   (`pg_basebackup -Ft -X fetch`), requires and verifies `backup_manifest` and the
   fetched WAL, encrypts the portable bundle, creates relocatable checksums,
   verifies every remote object, and securely removes temporary plaintext.
   Retrieve it and verify it in isolation.
9. Create pre/post markers around a recorded recovery target, archive actual WAL,
   recover into isolated PostgreSQL with `restore_command`, and prove the pre
   marker exists while the post marker does not. Verify every shared database and
   application-role connection. Publish only sanitized evidence.
10. Only after PITR PASS may the middleware release enter write freeze.

Rollback: if PostgreSQL, archiving, or any consumer fails, restore the captured
configuration and restart only within the approved window. Revalidate all
consumers. Do not migrate middleware. Preserve failed archive evidence without
secrets. Never restore over production and never create another writable primary.

Before installation, run `tests/integration/shared_postgresql_pitr_execution.sh`.
It exposes no public port and proves PostgreSQL 17 base backup, manifest,
encrypted-artifact relocation, restore-command WAL recovery, and timestamp PITR
with the pre-target marker present and the post-target marker absent.
