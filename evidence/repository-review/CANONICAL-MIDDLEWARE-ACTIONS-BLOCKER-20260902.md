# Canonical Middleware GitHub Actions startup blocker

Observed at 2026-09-02 on `Codestra-SRL/codestra-middleware`.

## Result

`FAIL` — protected release CI cannot start.

The last successful push workflow was run `33559556597` at source
`61e5948f9c800f4dd587cce75a332b617f418a0c`. Every eligible push inspected
after that point produced a zero-job `startup_failure` under synthetic workflow
ID `347945243`, whose API record has an empty name, path `BuildFailed`, and
state `deleted`. The current protected merge
`167bd6221911ec3fa988d719eb259646fa90f296` produced run `33665848148` with
the same result.

Repository workflow files are present and YAML-parseable, Actions is enabled,
and the expected push workflow remains registered as active. The organization
billing API reports an Actions organization budget with:

- `budget_amount: 0`
- `prevent_further_usage: true`

No billing setting was changed during remediation. Changing that budget can
authorize paid usage and therefore requires the organization billing owner.

## Required owner action

- Owner: `Codestra-SRL` organization billing owner
- Repository: `Codestra-SRL/codestra-middleware`
- Service: GitHub Actions release and exact-head CI
- Action: establish an approved non-zero Actions budget or other approved
  Actions entitlement, preserving fail-closed CI requirements.
- Validation: push a harmless protected-PR head, prove the registered exact
  workflows create real jobs and pass, then prove a protected-main merge starts
  `source-lock-candidate-build.yml` without a synthetic `BuildFailed` run.

Until that validation succeeds, canonical Middleware release publication,
source-lock advancement, staging promotion, and production promotion remain
blocked.
