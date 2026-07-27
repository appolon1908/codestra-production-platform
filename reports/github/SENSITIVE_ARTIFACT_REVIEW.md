# Sensitive Artifact Review

Generated UTC: 2026-07-27.

## Excluded runtime artifacts

- `evidence/crm-lead-campaign-invariant-20260725T185407Z/backup/codestra_master_v2_staging.prechange.pgcustom`
  is a 4,163,663-byte PostgreSQL backup and must not be staged.
- `.vicidial-staging-repo.tar.gz` is a generated archive and is ignored.
- `config/application-server-a.env` is protected local configuration and is
  ignored.
- Python caches, test caches, runtime data, volumes, recordings, filestore
  content, logs, archives, and build output are excluded by policy.

## Evidence policy

Existing evidence remains in place and was not deleted. Evidence directories
require file-by-file classification before any inclusion because prior
credential-remediation reports and database snapshots may contain operational
metadata or sensitive artifacts.

## Gate

`SENSITIVE_ARTIFACT_REVIEW=PASS_FOR_CURATION`

This permits source-only staging. It does not permit blanket staging of
`evidence/`, `reports/`, backups, or generated archives.
