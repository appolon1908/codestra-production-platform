# Sensitive Artifact Review

Generated UTC: 2026-07-27.

The full working tree was reviewed for database exports, archives, runtime
state, caches, evidence backups, logs, and large binaries. Twelve sensitive-
extension or large-file candidates are listed in
`SENSITIVE_ARTIFACT_INVENTORY.csv`.

Database backups (`.pgcustom`), SQL/schema exports, generated archives, evidence
backup directories, caches, scratch candidates, remote-edit workspaces, locks,
and runtime pointer files are ignored and excluded from staging. In particular,
the 4,163,663-byte PostgreSQL backup under the campaign-invariant evidence tree
is ignored and must not enter Git.

Existing artifacts were preserved in place; none were deleted, reset, or moved.
The protected configuration backup and pre-curation Git inventory are stored
outside Git under `/root/codestra-update-backups/20260727T202944Z`.

`SENSITIVE_ARTIFACT_REVIEW=PASS_FOR_CURATED_STAGING`
