# Canonical Middleware protected-CI blocker (refreshed)

Captured: 2026-09-03
Repository: `Codestra-SRL/codestra-middleware`

PR #283 (`e48ec614a2da680802ee106e271b52f3006e72dc`) and PR #284
(`0f877f7b04d627ff35c0528829553db99dfc3326`) are approved and report
`MERGEABLE`, but neither has a completed required check. `gh pr checks` reports
no checks for either branch.

The latest exact-head workflow dispatch for PR #283 is run `33698014234`.
GitHub reports:

- status: `completed`
- conclusion: `startup_failure`
- jobs: `0`
- event: `workflow_dispatch`

The preceding PR #284 dispatches also terminate with `startup_failure`. This is
an Actions/org execution failure before any test, security, provenance, or
exact-head job starts; it is not evidence that the PRs pass.

The GitHub API also returns HTTP 403 with “Upgrade to GitHub Pro or make this
repository public to enable this feature” for the private repository's branch
protection and ruleset endpoints. No protection bypass was attempted.

## Required action

Organization/repository owner must restore a permitted GitHub Actions execution
plan (and API visibility for protection read-back) or provide an approved
equivalent protected runner. Then rerun exact-head CI for both PRs and read back
all required checks and protection state.

## Safety state

Neither PR was merged or deployed. Server 65 and SSH were not changed.

`SOURCE_AUTHORITY=UNVERIFIED`
`PRODUCTION_CHANGED=NO`
`CALLS_PLACED=0`
