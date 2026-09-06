# Middleware production authority decision — 2026-09-03

## Status

```text
TARGET_SERVER=65.109.65.169
PRODUCTION_SOURCE_LOCK=FAIL
CANONICAL_MIDDLEWARE_AUTHORITY=UNRESOLVED
DEPLOYMENT_AUTHORIZED=false
PRODUCTION_CHANGED=false
SSH_CHANGED=false
EXTERNAL_EFFECTS_ENABLED=false
```

## Current production authority

```text
repository=Codestra-SRL/codestra-middleware
source_sha=f199b6c40f4e467979e9a8b255a0e686321a182d
image=ghcr.io/codestra-srl/codestra-middleware@sha256:ec2cf4ca73ff072fbdd48bda108a60f103526cb3e97a721abdf38435b010908b
migration_head=0056_klyrow_delivery_events
```

This remains the recorded production authority until a protected convergence or an explicitly certified migration changes it.

## New signed Appolon compatibility candidate

```text
repository=appolon1908-hue/Middleware-
protected_source_sha=1aa4d505846b7494aff94bec3d7ea68c895e2dd3
image=ghcr.io/appolon1908-hue/codestra-middleware@sha256:cec8b5a1b0e713857be1dbc94b73780bf9ae1a200d0901f95cb62193b9c2f504
migration_head=0009_observability_incidents
release_id=1aa4d505846b-cec8b5a1b0e7
release_run=33767657962
production_promotion_gate_run=33767951234
release_artifact_digest=sha256:cfd5ef83132da1683c0c053e7025739aa4c2747344aa7fc1feed48bf838a566a
sbom_sha256=sha256:87cab4a84d73ddff1acb198560e872b882f3cd6cdcce1a4b046b7a2d3f3a9049
contracts_sha256=sha256:2d3033d1819fb1d92c9da69b21e059e5e3c8c5217d5236f2d7536af9cd850ef3
migrations_sha256=sha256:6bd0d1ba307e51b5fd1705b8f93ed7d5edc1a9f80e74cbb4fa9a12e413603f58
runtime_profiles_sha256=sha256:c46c2bf17e955de663c271b33b95e2256fbecea9607ee5fcb29422605a799b84
fixable_high_or_critical_vulnerabilities=0
external_effects_default=disabled
```

The image is usable as compatibility and isolated-staging evidence. It is not automatically the canonical production Middleware because its repository lineage and migration head differ from the current production authority.

## Canonical convergence blocker

```text
repository=Codestra-SRL/codestra-middleware
pull_request=283
head_sha=e48ec614a2da680802ee106e271b52f3006e72dc
actions_run=33667817256
actions_conclusion=startup_failure
blocker=ORGANIZATION_ACTIONS_BUDGET_PREVENTS_JOB_CREATION
image_digest=MISSING
deployment_authorized=false
```

The connector has no write authority in the Codestra-SRL organization. Billing, Actions-budget restoration, exact-head reruns, approval, and protected merge must therefore be performed by an authorized organization administrator and reviewer.

## Permitted resolution paths

### Preferred path: retain Codestra-SRL as canonical

1. Restore a positive GitHub Actions budget for the Codestra-SRL organization.
2. Rerun every required exact-head check for PR #283.
3. Obtain independent approval on the unchanged final head.
4. Merge through normal protection.
5. Build an immutable image from the protected merged SHA.
6. Generate and verify SBOM, provenance, signature, configuration and contract digests, migration head, and rollback digest.
7. Certify that image in protected isolated staging.
8. Update the source lock and full-core BOM from generated evidence.

### Alternate path: migrate authority to Appolon

This path requires an explicit protected migration, not a documentation-only declaration:

1. Prove complete API and event-contract parity.
2. Produce a schema mapping between migration heads `0056_klyrow_delivery_events` and `0009_observability_incidents`.
3. Restore a representative production backup into isolated staging.
4. Execute the migration and verify row counts, constraints, audit history, inbox/outbox state, idempotency records, dead letters, encrypted webhook bodies, and tenant isolation.
5. Prove rollback to the Codestra-SRL image and schema without data loss.
6. Run the exact 29-route, identity, recovery, and no-effect staging certification.
7. Obtain protected approval for the authority change.
8. Update the source lock, signed full-core BOM, and production operator trust tuple atomically.

## Prohibited shortcut

Do not silently replace `Codestra-SRL/codestra-middleware` with `appolon1908-hue/Middleware-` merely because the Appolon image is newer and signed. A signed image does not prove compatibility with a different database lineage, operational contract, or production state.

## Required exit gates

```text
CANONICAL_MIDDLEWARE_REPOSITORY=<one repository>
PROTECTED_SOURCE_SHA=<exact SHA>
IMAGE_DIGEST=sha256:<64 hex>
MIGRATION_HEAD=<exact head>
SBOM=PASS
PROVENANCE=PASS
SIGNATURE=PASS
API_CONTRACT_PARITY=PASS
TENANT_ISOLATION=PASS
REPRESENTATIVE_RESTORE=PASS
SCHEMA_DATA_INTEGRITY=PASS
ROLLBACK=PASS
STAGING_CERTIFICATION=PASS
FULL_CORE_BOM=PASS
OPERATOR_TRUST=PASS
```

Until every applicable gate passes:

```text
PRODUCTION_SOURCE_LOCK=FAIL
DEPLOYMENT_AUTHORIZED=false
PRODUCTION_MUTATION=NO
```
