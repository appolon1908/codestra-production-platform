# Appolon Middleware production authority migration — 2026-09-03

## Decision boundary

Prepare `appolon1908-hue/Middleware-` as the canonical Middleware source authority for the next protected release. Runtime deployment remains prohibited until exact-head CI, independent review, protected staging, backup/restore, rollback rehearsal, and the read-only canary all pass.

Retain `Codestra-SRL/codestra-middleware` as the exact former rollback authority. Do not silently mix its source SHA, image digest, or migration head with the Appolon candidate.

## Exact signed candidate

- Repository: `appolon1908-hue/Middleware-`
- Source SHA: `1aa4d505846b7494aff94bec3d7ea68c895e2dd3`
- Git tree: `f67ed2eb19afc67dbe51624b5ba6298ec5dc5e32`
- Image: `ghcr.io/appolon1908-hue/codestra-middleware@sha256:cec8b5a1b0e713857be1dbc94b73780bf9ae1a200d0901f95cb62193b9c2f504`
- Migration head: `0009_observability_incidents`
- Release ID: `1aa4d505846b-cec8b5a1b0e7`
- Signed release run: `33767657962`
- Artifact: `signed-middleware-release-1aa4d505846b7494aff94bec3d7ea68c895e2dd3-33767657962-1`
- Artifact digest: `sha256:cfd5ef83132da1683c0c053e7025739aa4c2747344aa7fc1feed48bf838a566a`
- Workflow identity: `https://github.com/appolon1908-hue/Middleware-/.github/workflows/release.yml@refs/heads/main`
- OIDC issuer: `https://token.actions.githubusercontent.com`
- SPDX SBOM SHA-256: `87cab4a84d73ddff1acb198560e872b882f3cd6cdcce1a4b046b7a2d3f3a9049`
- Grype report SHA-256: `a5275e506c7d5048711c6b76b6c879885aea053c3753fdf6599b78bc51dd680d`
- Release manifest SHA-256: `760bc3197f55bc59a542b736506d686fb3081c95ebc3f3757c16e1ff61fcf049`
- Sigstore bundle SHA-256: `7d24a0d5c76f9d44963312157738ddd888bbe680966c67c4f9abe07c566d9958`
- Grype vulnerability matches: `0`

The exact run contains two GitHub artifacts: one Buildx record and one signed release bundle. The migration workflow must select the signed bundle by its exact source/run prefix and verify its artifact digest. It must not require the entire run to contain only one artifact.

The signed release bundle contains exactly:

```text
middleware.grype.json
middleware.spdx.json
release-manifest.v1.json
release-manifest.v1.sigstore.json
```

It does not contain the legacy `RELEASE.env`, CycloneDX SBOM, standalone provenance JSON, or upstream OpenVEX. Platform provenance and OpenVEX evidence must therefore be deterministic derivatives of the cryptographically verified manifest and zero-match Grype report; unrelated hashes must never be mislabeled.

## Safety boundary

This authority migration changes repository release controls only. It does not deploy a container, execute a database migration, alter SSH, route production traffic, enable a business write, call a provider, send email or SMS, place a PSTN call, write to Odoo, or activate n8n delivery.

```text
LIVE_SMS_DELIVERY=false
LIVE_EMAIL_DELIVERY=false
LIVE_PSTN_DIALING=false
LIVE_WRITE=false
ODOO_WRITE=false
N8N_DELIVERY_ENABLED=false
CALLBACK_DISPATCH=false
CALLS_PLACED=0
DEPLOYMENT_AUTHORIZED=false
PRODUCTION_SOURCE_LOCK=FAIL_UNTIL_RUNTIME_GATES_PASS
```
