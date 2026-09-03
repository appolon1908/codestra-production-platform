# Appolon Middleware production authority migration — 2026-09-03

## Decision

Select `appolon1908-hue/Middleware-` as the Middleware release authority for the
next protected staging certification. This is an explicit authority migration,
not a silent substitution and not a production deployment.

The former `Codestra-SRL/codestra-middleware` tuple remains a historical rollback
reference only. PR #283 remains an unmerged source reference because its required
`codestra/required-ci` workflow could not start while the organization Actions
entitlement blocked job creation. That external failure is not represented as a
passing check.

## Exact selected candidate

| Field | Value |
| --- | --- |
| Repository | `appolon1908-hue/Middleware-` |
| Source SHA | `1aa4d505846b7494aff94bec3d7ea68c895e2dd3` |
| Source tree | `f67ed2eb19afc67dbe51624b5ba6298ec5dc5e32` |
| Image | `ghcr.io/appolon1908-hue/codestra-middleware@sha256:cec8b5a1b0e713857be1dbc94b73780bf9ae1a200d0901f95cb62193b9c2f504` |
| Migration head | `0009_observability_incidents` |
| Release run | `33767657962`, attempt `1` |
| Artifact ID | `9898309168` |
| Artifact name | `signed-middleware-release-1aa4d505846b7494aff94bec3d7ea68c895e2dd3-33767657962-1` |
| Artifact ZIP SHA-256 | `cfd5ef83132da1683c0c053e7025739aa4c2747344aa7fc1feed48bf838a566a` |
| Release manifest SHA-256 | `760bc3197f55bc59a542b736506d686fb3081c95ebc3f3757c16e1ff61fcf049` |
| Sigstore bundle SHA-256 | `7d24a0d5c76f9d44963312157738ddd888bbe680966c67c4f9abe07c566d9958` |
| SPDX SBOM SHA-256 | `87cab4a84d73ddff1acb198560e872b882f3cd6cdcce1a4b046b7a2d3f3a9049` |
| Grype report SHA-256 | `a5275e506c7d5048711c6b76b6c879885aea053c3753fdf6599b78bc51dd680d` |
| Signer identity | `https://github.com/appolon1908-hue/Middleware-/.github/workflows/release.yml@refs/heads/main` |
| OIDC issuer | `https://token.actions.githubusercontent.com` |
| Fixable high/critical matches | `0` |

The protected release workflow downloads artifact ID `9898309168` directly,
verifies its archive digest and metadata, verifies the exact four-file evidence
set, validates every manifest and tuple binding, verifies the image signature,
BuildKit provenance attestation, SPDX attestation, and signed release-manifest
bundle, then reads the image source labels and migration head before generating
the platform release.

## Required staging migration proof

The selected source uses migration head `0009_observability_incidents`, while the former authority
used `0056_klyrow_delivery_events`. Before any production deployment, an isolated
staging restore must prove:

1. the actual production-compatible database backup restores successfully;
2. the selected migration lineage reaches exactly `0009_observability_incidents`;
3. application health, readiness, version, capabilities, metrics, tenant
   isolation, and all 29 Kong route checks pass;
4. no email, SMS, PSTN call, Odoo write, n8n external delivery, social
   publication, advertisement, payment, or other provider effect occurs;
5. rollback to the former exact source/image/database decision succeeds within
   the approved RTO and RPO;
6. the selected candidate can be restored after the rollback rehearsal without
   source, digest, schema, or data-integrity drift.

## Remaining blockers

This migration resolves the repository-level Middleware authority split only.
The global `PRODUCTION-SOURCE-LOCK.yaml` remains `FAIL` because:

- 24 custom workloads still lack source-bound signed registry digests;
- the runtime candidate matrix remains deployment-disabled;
- the protected isolated staging host is not created and verified;
- the staging environment variables, secrets, and endpoint manifest are absent;
- backup, restore, two-way rollback, and the one-percent production canary have
  not been executed.

## Safety boundary

```text
PRODUCTION_DEPLOYMENT_AUTHORIZED=false
PRODUCTION_TRAFFIC_CHANGED=false
LIVE_EMAIL_DELIVERY=false
LIVE_SMS_DELIVERY=false
LIVE_PSTN_DIALING=false
ODOO_WRITE=false
N8N_DELIVERY_ENABLED=false
SOCIAL_PUBLISHING_ENABLED=false
LIVE_ADVERTISING_ENABLED=false
PAYMENT_EXECUTION=false
```

Merging this source change does not contact a server, run a database migration,
modify SSH, route traffic, or enable an external effect.
