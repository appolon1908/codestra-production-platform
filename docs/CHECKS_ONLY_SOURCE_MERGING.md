# Checks-only source merging

Scope: `appolon1908-hue/codestra-production-platform`, default branch
`release/production-activation`, ruleset `22197395` only. This document describes
the intended policy. A source commit does not change live GitHub settings.

## Enforced CI behavior

Platform validation and secret diagnostics run on every pull request. The
read-only `production-gate` requires their workflows and check jobs to actually
succeed, waits for other observed workflows/checks/statuses, rejects malformed or
unavailable API evidence, and refuses a changed head, advanced base, or branch
behind its target. Required jobs cannot pass by being skipped or neutral. A new
`checks-only-policy` context succeeds only after the hardened gate succeeds.

Older queued PRs do not have that context. Once the owner makes it required,
they must integrate this source change and receive new successful CI instead of
merging immediately on the old permissive gate.

## One-time owner-authorized cutover

Use the owner's existing GitHub CLI session, never another reviewer's password,
PAT, or impersonated identity. Repository Administration write permission is
required. The ChatGPT managed integration's denial of administration access is
not cured by committing this script or by changing ChatGPT prompt permissions.

From the exact bootstrap PR checkout, first run the read-only preflight:

```sh
python3 tools/configure_checks_only_merge.py \
  --bootstrap-pr PR_NUMBER --expected-head EXACT_PR_HEAD
```

After CI succeeds, apply the owner's already-authorized policy:

```sh
python3 tools/configure_checks_only_merge.py \
  --bootstrap-pr PR_NUMBER --expected-head EXACT_PR_HEAD --apply
```

The command verifies the four CI source files against that exact remote head,
checks the current base and successful CI, and saves before/after settings in a
private temporary evidence directory. It first adds strict required checks
bound to the observed GitHub Actions app, while retaining the existing review
requirement. It then sets applicable classic review settings and the named
ruleset to zero required approvals. Existing required checks and all unrelated
classic protections are preserved; signed commits, resolved conversations,
linear history, no force pushes, no branch deletion, and squash-only PR merges
remain required. Unexpected scope, bypass actors, additional mandatory-review
rules, or denied API access stop the change.

Only the bootstrap PR is submitted to the normal squash-merge endpoint with
its expected head. The command cannot bypass a rejection, forge an approval,
dismiss a review, or merge unrelated PRs. If an operation fails, inspect the
snapshots: the policy change can be partial. Do not remove the new check gate
just to force completion. Restore a prior policy only through an authorized
owner change using `before.json`; never guess previous settings.

### Concurrent administrators

Pause other automated policy writers and coordinate with administrators before
running the cutover. Immediately before the final whole-ruleset update, the
command reads the ruleset again and requires it to equal the strengthened
policy. This check occurs after classic review reconciliation. A changed,
denied, or malformed read stops the final write and bootstrap merge; it never
retries the stale payload or rolls back over an administrator's intervening edit.
Earlier writes can remain applied, so retain and inspect the evidence directory.

The read/compare/write sequence is not an atomic API lock. It detects changes
visible at that final read but cannot prevent a writer racing the subsequent
request. Keep the policy-administration window exclusive; do not claim full
concurrency safety from a successful comparison alone.

## Routine integration

For each eligible, non-draft PR, the repair agent updates the branch with the
latest protected target, fixes actual defects, and reruns tests. Findings are
resolved only when their fixes are verified. Use normal squash auto-merge with
an expected head; process integration serially so each next branch includes the
previous merged change. Auto-merge enrollment is per PR, not automatic merely
because the repository enables it. This change does not install an unattended
repair agent or a new GitHub App.

Workflow-write permission remains security-sensitive: check names and a passing
suite alone do not prove gate code cannot be altered by a contributor. Keep
workflow and merge-policy edits owner-controlled; a dedicated merge-policy app
or independently governed required workflow is the stronger trust boundary.
Do not grant an AI repair job repository administration or release secrets.

## Deployment boundary

Source merges do not authorize installation, maintenance windows, key rotation,
production database migrations, live email/SMS/dialing, or traffic activation.
Existing automatic post-merge release workflows may run; this command dispatches
no deployment, release, or server operation. Missing runtime authority remains
missing even after source CI succeeds.

## Evidence

Run `python -m pytest -q tests/test_checks_only_merge.py tests/test_checks_only_cutover_concurrency.py`
for offline policy, negative CI, and cutover-ordering regressions. Those tests
use an in-memory API and do not claim that GitHub settings were changed; only
successful API mutation and readback establish live activation.
