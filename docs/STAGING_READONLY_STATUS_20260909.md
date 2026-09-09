# Staging-readonly configuration status — 2026-09-09

The live GitHub environment permits deployment only from the branch
`release/production-activation`. The canary ceiling is `1` percent and the Kong
route-count constant is `29`. Read-back is recorded in
[`20260909-environment-readback.json`](../evidence/staging-readonly/20260909-environment-readback.json).
This confirms repository environment configuration, not deployment certification.

The initial environment update returned HTTP 422 because sending absent reviewer
fields (`reviewers: null`, `prevent_self_review: false`) triggered a reviewer-rule
plan entitlement check. The applied request omitted absent reviewer/timer fields
and preserved the deployment branch restriction. The configurator fix in PR #324
makes that behavior reproducible and refuses malformed existing reviewer/timer
rules instead of clearing protections. Existing reviewer and timer protections
remain preserved when present.

The environment currently has branch protection only. Required deployment
reviewers are not configured and were rejected under the current plan. They must
not be represented as enabled. See
[GitHub environment API availability](https://docs.github.com/en/rest/deployments/environments).

Deployment remains blocked by the missing approved isolated host and identity,
candidate/endpoint manifests, staging credentials, eight nonconstant environment
variables, and runtime certification. No secret values were read or injected.
The release-signing public key exists as a repository-scoped secret; the staging
environment itself lists zero secrets. Issue #240's seven staging secrets remain
outstanding.

Read-only Server A inspection through the existing pinned SSH route confirmed
hostname `middleware`. The installed operator's status record was
`/var/lib/codestra-production-operator/evidence/20260909T020933Z-3946553-status.json`.
It reported disabled runtime calling flags and zero active calls/channels, but
also failed units. Its `PASS` result is an operator-status result, not overall
production certification.

The subsequent unit inventory found eleven failed backup, restore, or metrics
units. Selected control-plane, both Middleware authorities, WebSocket, and
Prometheus containers were unhealthy; their most recent health probes exited
with `-1` before the container probe process could start. This does not establish
the application failure cause or prove that no historical PSTN calls occurred.
No runtime changes, backup retries, deployments, or PSTN calls were performed.

Issues #228 and #240 remain open until their external prerequisites are supplied.
The broader calling and production certification missions also remain blocked.
