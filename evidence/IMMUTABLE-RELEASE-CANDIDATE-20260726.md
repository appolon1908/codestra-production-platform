# Immutable release-candidate reconciliation

Evidence cutoff: `2026-07-26T00:10:00Z`

No release was promoted. The work completed the non-destructive inventory,
preservation, clean-source selection, current vulnerability refresh, and
independent-build audit. It found blocking source, registry, vulnerability,
and reproducibility conditions that prevent an exact whole-platform candidate
from being represented as immutable.

## Repository inventory and preservation

Fifteen release/evidence repositories were inventoried. Only
`/root/odoo19-call-center-migration` was clean. Three repositories are unborn,
and ten repositories contain tracked, staged, or untracked work. The active
Odoo integration tree mounted in production is dirty.

Every repository was preserved non-destructively in:

`/root/codestra-release-preservation-20260726T000436Z`

The protected package contains status snapshots, binary tracked/index patches,
worktree archives, HEAD/branch records, and Git history bundles where a commit
exists. It contains 103 files (33,230,447 bytes); every entry in `SHA256SUMS`
passes. Dependency caches and generated browser/build output were excluded
from source archives. No reset, checkout-overwrite, or clean operation was
used.

## Clean attributable source selections

| Component | Commit | State |
|---|---|---|
| Odoo integration add-ons | `3f2eff50254d62cb42531fe72e9d0be2cdb1a7d2` | clean commit selected; mounted worktree remains dirty |
| Odoo call-center add-ons | `5f5cb6af298086d0213bfcd0ba77b6d5a855af5a` | clean |
| Middleware reproducibility fix | `7671cb5e35282e7adb1f5b39a5c3c56a07352a2a` | clean isolated worktree |
| n8n workflows | `b39f26f1b5a58d0894296fbc9aa55adfc6a93313` | clean commit selected; operational worktree remains dirty |
| OpenUpgrade 19 | `edaed4778e986e5d56a8c8f5551e91398ec9513c` | clean tool commit |

The middleware fix pins the previously floating transitive Python packages,
normalizes installed-file timestamps, and adds a regression test. The
regression test passed. It was committed on isolated branch
`release/immutable-20260726`; the dirty operational worktree was not modified.

## Images and vulnerability evidence

Previously tested Odoo 19:

`odoo@sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5`

The refreshed scan found one fixable high-severity Node.js `postcss` finding.
The current Odoo 19 image resolves it:

`odoo@sha256:e415f9924395e7521245813135112f264b9222bcde3b1d3c2ee9ff073081540a`

Its refreshed scan reports zero high and zero critical findings. It is not the
final candidate because the representative migrated database test suite has
not been repeated against this new digest.

The exact clean middleware baseline
`codestra/gate3a-release@sha256:23ebbcdf07eb475adf628175c9450056188a4fdcaebff6e8e5716245df5581c0`
reports 21 high and zero critical findings. All 21 have an empty scanner
`FixedVersion`. The unsigned risk packet is
`evidence/IMMUTABLE-RELEASE-RISK-PACKET-20260726.md`.

CycloneDX SBOMs, raw Trivy JSON, build logs, image identifiers, source
manifests, and checksums are stored at:

`/root/codestra-release-candidate-20260726T000539Z`

## Independent clean builds

The exact source commit was exported twice to fresh directories. After
normalizing source timestamps, both source manifests matched:

`7abc22ed47faf69ec6bda2dd75072075e89c1eb56e617194a6ba7a548bd16c08`

The two no-cache images did not match:

- build E: `sha256:e6b6c94b70be7495ab93a255a348886cab13d5bbf58b8c8d9ca7fb90d528db15`
- build F: `sha256:dab3d813e505f4ec8aa02dd8003e3c5cee0b8f50dac090568c10ae3e62cd6873`

Exported rootfs file content matched; OCI layer metadata did not. Therefore
whole-image reproducibility is not established by today's independent builds.
Local image identifiers are evidence only and are not registry artifacts.

## Release versions

Database migration versions selected from middleware commit `7671cb5`:
`0001` through `0006`.

Odoo integration modules at `3f2eff5`:

- `codestra_base` `19.0.1.0.0`
- `codestra_integration_hub` `19.0.1.0.0`
- `codestra_vicidial_connector` `19.0.1.0.0`
- `codestra_vicidial_crm` `19.0.2.0.0`

Odoo call-center modules at `5f5cb6a`: `call_center_campaign`
`19.0.2.0.0`; the other 15 selected modules are `19.0.1.0.0`.

n8n workflow source commit: `b39f26f1b5a58d0894296fbc9aa55adfc6a93313`.
Clean Git archive SHA-256:
`eac9e012816da8f30e99ad8f75eedcc892bb8e956eca2bff6229490906d78aaf`.

Monitoring-rule aggregate SHA-256:
`0fb96f9183380dd21a9b23f7d9778c8767a32c8196f72a2078cc0aaae42e6d5a`.

Production Compose SHA-256:
`4ccab98236ed1cd9ef8d243710c3cad2a8b663cef9a94c0c278d7903086d60a8`.
Reverse-proxy configuration SHA-256:
`249f97473fce02b2e1e1048cce0ef0b8b441f7c843c73d356c70adbd46c0d849`.

## Registry and rollback

No approved private-registry endpoint or scoped credentials are configured.
Docker is configured only for the public Docker Hub index. Consequently no
internal image was pushed, pulled by an approved registry digest, rescanned
after pull, or promoted. Current production still references mutable local
middleware and reverse-proxy tags.

The verified rollback package is
`/opt/codestra/backups/odoo19-final-precutover-20260725T223823Z`. Its database,
filestore, configuration, and migrated-database checksums pass. A prior
isolated rollback restored the database/filestore, registry, and login in 14
seconds. This mission did not redeploy it because no promotable immutable
candidate exists to redeploy afterward; performing only the destructive half
of that drill would not satisfy the requested rollback/candidate cycle.

## Gates

```text
DIRTY_REPOSITORY_GATE=BLOCKED_UNATTRIBUTED_AND_UNCOMMITTED_RELEASE_INPUTS
VULNERABILITY_REMEDIATION_GATE=BLOCKED_UNFIXED_HIGHS_AWAITING_EXTERNAL_DECISION
REGISTRY_DIGEST_GATE=BLOCKED_APPROVED_PRIVATE_REGISTRY_UNAVAILABLE
REPRODUCIBILITY_GATE=FAIL_INDEPENDENT_IMAGE_DIGEST_MISMATCH
IMMUTABLE_RELEASE_GATE=BLOCKED_NO_PROMOTABLE_WHOLE_PLATFORM_DIGEST
ROLLBACK_ARTIFACT_GATE=BLOCKED_CANDIDATE_REDEPLOYMENT_UNAVAILABLE
```

