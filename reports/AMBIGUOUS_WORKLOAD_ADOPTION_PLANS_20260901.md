# Ambiguous workload adoption plans

Date: 2026-09-01

These are sanitized source-adoption plans. No dirty worktree was pushed, no
runtime was rebuilt or replaced, and no production service was restarted.
Human review is required before any local implementation is adopted.

## `codestra-beyvra-email-api-1`

- Candidate repository: `Codestra-SRL/codestra-middleware`
- Local evidence root: `/root/beyvra-email-middleware`
- Local-only files: none reported by Git
- Protected-only files: all subsequent protected-main changes outside the
  local feature branch
- Conflicts: modified email worker, Beyvra Compose, environment example,
  dependency declarations, and lock file
- Secret-bearing files excluded: all environment-value and credential files
- Plan: create a clean middleware adoption branch, replay only reviewed Beyvra
  deltas, regenerate the dependency lock through CI, and require provider-write
  negative tests. Do not copy the dirty worktree.

## `codestra-email-reseller-api-1`

- Candidate repository: `appolon1908-hue/codestra-production-platform`
- Local evidence root: `/root/codestra-odoo-middleware-functional`
- Local-only files: `deploy/email-reseller/`, `email_reseller_service/`, and
  related tests/reports
- Protected-only files: all current protected production-platform material
- Conflicts: the local worktree also contains unrelated modified and untracked
  production-integration work
- Secret-bearing files excluded: runtime environment values, provider
  credentials, generated artifacts, and evidence payloads
- Plan: import only the email-reseller source, tests, Dockerfile, and
  parameterized deployment files into a clean branch; require dry-run provider
  tests and independent review.

## `codestra-mail-api-mail-api-1`

- Candidate repository: `appolon1908-hue/codestra-production-platform`
- Local evidence root: `/root/codestra-production-completion`
- Local-only files: mail API Dockerfile and Compose plus reviewed Keycloak/Kong
  declarative configuration and n8n workflow definitions
- Protected-only files: current protected production-platform authority
- Conflicts: evidence root is a dirty preservation worktree with unrelated
  WebSocket and certification changes
- Secret-bearing files excluded: credential values, tokens, mail data,
  generated evidence, and runtime state
- Plan: extract only the mail-platform source/configuration through a clean
  import, parameterize all identities, and require negative delivery tests.

## `codestra-provisioning-service-provisioning-service-1`

- Candidate repository: `appolon1908-hue/codestra-provisioning-service`
- Protected branch: `main`
- Protected head at comparison: `0a1998aa7bbe8b38481ac07fe036055c6191c5c5`
- Local evidence root: `/root/codestra-provisioning-running-source-20260819`
- Local-only files: none established as authoritative
- Protected-only files: mailbox/readiness implementation and protected
  deployment, governance, preflight, and SQLite recovery controls
- Conflicts: adapters, config, contracts, engine, logging, main, repository,
  security, SIP browser, and dependency lock differ
- Secret-bearing files excluded: all runtime environment and secret material
- Plan: retain the recovery record's `runtime equivalence unproven` decision.
  A clean candidate must be built from protected main and compared by behavior
  and artifact evidence before replacement; local source must not override it.

## `codestra-reseller-portal-portal-1`

- Candidate repository: `appolon1908-hue/codestra-production-platform`
- Local evidence root: `/root/codestra-odoo-middleware-functional`
- Local-only files: `deploy/reseller-portal/`, `reseller_portal/`, and related
  tests/reports
- Protected-only files: all current protected production-platform material
- Conflicts: local worktree contains unrelated modified and untracked changes
- Secret-bearing files excluded: OIDC client secrets, database passwords,
  environment values, customer data, and runtime state
- Plan: import only portal application/tests and parameterized deployment files
  on a clean branch; require tenant-isolation, OIDC, and negative authorization
  tests before adoption.

## Common adoption gate

Each future adoption PR must have exact-head CI, security and secret scans,
CODEOWNER review, zero substantive unresolved threads, and protected merge. It
must emit an immutable candidate digest with Git revision/source/version labels,
SBOM, provenance, and vulnerability results. Merge does not authorize deployment.
