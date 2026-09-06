# Ambiguous workload adoption plans

Date: 2026-09-01

These are sanitized source-adoption plans. No dirty worktree was pushed, no
runtime was rebuilt or replaced, and no production service was restarted.
Human review is required before any local implementation is adopted.

## `codestra-beyvra-email-api-1`

- Candidate repository: `Codestra-SRL/codestra-middleware`
- Reviewed clean snapshot: PR `Codestra-SRL/codestra-middleware#277`, commit
  `39c153037f3b049b01a84cc3fb0940c08aa5346c`, tree
  `137aa59f4bd2a8eb1201a85747a2c77bdc1d467d`
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
- Reviewed clean snapshot: PR `appolon1908-hue/codestra-production-platform#171`,
  commit `fa752031b302f3ce7eaa746acc67e8c87143f27a`, tree
  `f92cfcab89668dd1e7de4cd15c17b482beddf975`
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
- Reviewed clean snapshot: PR `appolon1908-hue/codestra-production-platform#173`,
  commit `e1b412799701a6d88d7bef6e38fc52e7c7e7acf3`, tree
  `c54d26503e1f0aa1dad32272a3ad8a3e0de43934`
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
- Reviewed clean snapshot: PR `appolon1908-hue/codestra-provisioning-service#18`,
  commit `a82d191789006a701f78c8a3bf0c10357ddfbb00`, tree
  `17f8375e7e1354928d83bead2cc7e10dc8351d74`
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
- Reviewed clean snapshot: PR `appolon1908-hue/codestra-production-platform#172`,
  commit `74bef6f721ca76db3b21d5db679e5a2d4c11a396`, tree
  `3a7288f397cfd5b624593cd525c44f8381162f5d`
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
