# Backblaze to Hetzner backup migration

The selected destination is a private Hetzner Object Storage bucket using Restic.
This runbook records a completed bounded encrypted seed transfer and isolated
restore. It does not switch an existing backup job or certify independent
recovery, complete historical migration, retention, or production readiness.

## Destination and credentials

Create or select a private bucket in the intended Hetzner project. Record its
exact bucket name, location, retention policy and recovery-key custody.
Generate a dedicated S3 key pair in that project, with the required bucket
permissions. A Hetzner Cloud API token is not an S3 key pair.

The example uses fsn1 only as an example; fsn1, nbg1 and hel1 are accepted.
Use a bucket name made of lowercase letters, digits and hyphens. Replace the
uppercase bucket placeholder before validation.

Install the profile as /etc/codestra/backup/hetzner-restic.json, owned by root,
mode 0600, in a root-owned 0700 directory. The three referenced credential files
must also be root-owned regular files, mode 0600, in a root-owned 0700 directory.
Inject their values through the approved secret manager or a private terminal.
Keep credential values out of Git, shell arguments, logs and chat.
The validator opens the full directory chain without following symlinks and
rejects foreign owners and group/world-writable ancestors. Each immediate
parent must also be private. The validated Restic password is passed only in
the child environment, so Restic does not reopen its source path.

The Restic password is a recovery secret. Preserve the existing password when
copying the existing repository bytes. A new separately initialized repository
may use a new approved password, whose independent recovery custody must be
established before relying on it.

Run the reviewed source without modifying a live checkout:

    python3 operations/readiness/hetzner_restic_preflight.py --profile /etc/codestra/backup/hetzner-restic.json

This validates local configuration and credential-file protection without
contacting storage. The optional --check-repository flag reads existing
snapshot metadata with TLS validation, no local cache and no repository lock.
It reports only aggregate results and does not print remote errors, snapshot
paths or credentials. An uninitialized bucket or wrong Restic password will
fail that read; the command never automatically initializes a repository.
A successful read does not prove write access, bucket privacy, object-lock
retention, data integrity or an isolated restore.

## Migration and cutover gates

1. Inventory retained encrypted local backups and the old B2 repository. Preserve
   existing B2 configuration, credentials, encryption keys and backup history.
2. Validate the new bucket's private access, credential scope, intended location,
   capacity and retention against the selected account. Capture that evidence.
3. Choose an empty target prefix. For historical migration, first restore access
   to B2, then use a reviewed Restic repository-copy procedure. If B2 remains
   unreadable, seed the new repository from verified retained local encrypted
   backups and report old-history migration as incomplete.
4. Establish the new repository deliberately. Upload a bounded encrypted backup,
   bind the resulting snapshot ID, download it, compare ciphertext checksums,
   and complete an isolated decrypt/restore with independent key access.
5. Prepare source changes for each consumer before switching its installed
   configuration. The current inventory is below. Preserve existing source and
   configuration for rollback; do not place Hetzner keys in files named b2-*.
6. After normal review and release gates, switch the approved consumer profiles
   and schedules. Verify fresh successful backups and monitoring per workload.
   Resume retention only after its policy has been validated on the new target.
7. Retire the old destination only after retained-history reconciliation and
   recovery verification. This migration preparation authorizes no deletion.

| Consumer | Current authority and required change |
| --- | --- |
| Kong database backup and WAL | The Kong-owned scripts currently read /etc/codestra/backup/b2-*; promote provider-neutral credential references through the Kong repository before cutover. |
| Shared PostgreSQL base/WAL backup | Uses protected authority files including restic-repository, object-access-key-id, object-secret-access-key and object-region; bind the complete new tuple together. |
| Caddy, database certification, scraper/middleware | Current off-host jobs use an SSH destination. Moving these to S3 requires reviewed transport changes, rather than only changing the central Restic URL. |
| VICIdial | Preserve its independently encrypted configuration/database backups and verify the new off-host copy and isolated restore before production activation. |

## Discovery before the verified seed transfer on 2026-09-10

Core host 65.109.65.169 still selected the B2 S3 repository.
Its protected Hetzner Cloud token returned HTTP 401. The candidate
/etc/codestra/secrets/backup/object-storage.env was empty and had no installed
consumer. The legacy Robot endpoint returned STORAGEBOX_NOT_FOUND; that endpoint
only covers legacy inclusive Storage Boxes, so it does not establish that the
account has no modern Storage Box or Object Storage bucket. No Hetzner storage
was created, purchased or modified, and no backup job was switched.

## Official references

- [Hetzner bucket creation](https://docs.hetzner.com/storage/object-storage/getting-started/creating-a-bucket/)
- [Hetzner S3 credential creation](https://docs.hetzner.com/storage/object-storage/getting-started/generating-s3-keys/)
- [Hetzner Restic setup](https://docs.hetzner.com/storage/object-storage/howto-backups/restic/)
- [Hetzner bucket migration](https://docs.hetzner.com/storage/object-storage/getting-started/migrate-providers/)
