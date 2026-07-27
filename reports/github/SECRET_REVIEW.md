# Secret Review

Generated UTC: 2026-07-27.

## Scope and methods

The complete repository working tree was scanned, including tracked, untracked,
and ignored regular files. The review used targeted filename classification,
private-key, GitHub-token, AWS-key, JWT, and credential-assignment patterns.
Values were never written to reports; findings contain only category and a
16-character SHA-256 prefix.

- Text files scanned: 870
- High-confidence private-key/token findings: 0
- Heuristic credential-assignment findings: 29
- Protected environment values matching a finding fingerprint: 0
- Dedicated scanner availability: no `gitleaks`, `trufflehog`, or
  `detect-secrets` executable installed

The 29 heuristic findings were inspected in redacted form. They are variable
assignments, environment reads, synthetic test fixtures, deliberately wrong
test values, and redaction tests. Candidate/scratch/evidence paths are ignored
or excluded from the curated checkpoint. Files containing synthetic fixtures
remain subject to staged-diff review before any later inclusion.

`config/application-server-a.env` is ignored, mode `0600`, and was backed up
outside Git before review. No known live secret is approved for staging.

Detailed redacted results: `SECRET_SCAN_FINDINGS.csv`.

`SECRET_REVIEW=PASS_FOR_CURATED_STAGING_WITH_TOOLING_LIMITATION`
