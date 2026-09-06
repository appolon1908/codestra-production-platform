# Automated Production Gates

This repository supports protected, automated pull-request promotion without mandatory human pull-request approval while preserving deterministic source, security, rollback, and runtime-activation controls.

## Scope

The zero-review policy applies to **pull-request merge approval only**. It does not turn a source merge into permission to change production traffic, credentials, databases, providers, or external effects.

## Protected merge policy

- Required approving reviews: 0.
- Required Code Owner reviews: off.
- Required status context `validate`: success on the exact current head SHA.
- Every additional path-specific required check: success on the exact current head SHA.
- Strict/up-to-date protected branch requirement: on.
- Conversation resolution: on; unresolved review threads remain merge blockers.
- Draft pull requests: not mergeable.
- Force pushes and protected-branch deletion: blocked.
- Auto-merge: permitted only after all protected checks and conversations pass.
- Administrator bypass is not part of the normal release path.

Repository settings must implement these rules. This document is policy authority; it does not claim that a GitHub setting changed unless GitHub records that change.

## Exact-head automated evidence

Every automated merge must retain GitHub-verifiable evidence containing:

- repository and pull-request number;
- protected base branch and base SHA;
- exact pull-request head SHA;
- required workflow run IDs and URLs;
- final required-check conclusions;
- unresolved conversation count of zero;
- merge method, merge timestamp, and resulting protected-branch SHA.

A prior successful run does not approve a later head. Any new commit invalidates the earlier exact-head evidence and requires the checks to run again. Automated review comments are advisory, but an unresolved thread created from those comments is a protected merge blocker until the finding is fixed, rejected with evidence, or marked outdated and resolved.

## Runtime activation policy

A protected merge records source history only. Production promotion still requires source authority, immutable digest pinning, migration validation, rollback evidence, database backup and isolated restore where applicable, security checks, staging or synthetic certification, and a production read-only canary.

The GitHub `production` environment controls live-effect workflows. It is separate from pull-request review. A deployment must pass that environment before changing production. A later protected change may replace it only after defining and validating a machine-enforced equivalent. Removing pull-request reviews must not remove the deployment gate.

Server `65.109.65.169` must retain all of the following evidence:

- exact source SHA;
- immutable image digest and rollback digest;
- migration state;
- application contract parity;
- Kong routing validation;
- Caddy edge validation;
- Keycloak identity validation;
- integration evidence;
- environment-gate evidence;
- safety read-back.

SSH access controls must not be changed.

Live email, SMS, PSTN, social publishing, advertising, external model writes, n8n external-provider writes, trading, deposits, and withdrawals remain disabled unless a separately approved protected runtime-activation change enables the specific capability.

## Activation-packet status vocabulary

Activation packets must distinguish source merge from runtime approval:

```text
MERGE_GATE_STATE=PENDING_EXACT_HEAD_VALIDATION
PRODUCTION_ENVIRONMENT_GATE_STATE=PENDING
RUNTIME_ACTIVATION_GATE_STATE=PENDING_PRODUCTION_ENVIRONMENT_APPROVAL
```

After GitHub records the exact-head checks and protected merge, only `MERGE_GATE_STATE` may become `PASS`. `RUNTIME_ACTIVATION_GATE_STATE` remains pending until the production-environment gate and all runtime prerequisites are recorded by GitHub and the governed deployment workflow.
