# Codestra portfolio release-candidate blocker report — 2026-09-08

## Decision

```text
REPOSITORY_READINESS=BLOCKED
PLAN_READINESS=BLOCKED
RUNTIME_RECOVERY_READINESS=BLOCKED_NOT_REEXECUTED
DEPLOYMENT_AUTHORIZATION=NOT_AUTHORIZED
CANDIDATE_CREATED=NO
PLAN_DISPATCHED=NO
STAGING_DISPATCHED=NO
CANARY_DISPATCHED=NO
PRODUCTION_DISPATCHED=NO
EXTERNAL_EFFECTS_ENABLED=NO
```

An executable `config/releases/<release-id>.json` was deliberately not created.
The required evidence is incomplete and internally inconsistent. A release ID,
candidate hash, missing contract, check result, image digest, rollback identity,
approval, or recovery result was not inferred or copied from a different
lineage.

## Repository-first observation boundary

- Repository: `appolon1908-hue/codestra-production-platform`
- Protected branch: `release/production-activation`
- Protected head observed at the start of preparation:
  `b5d574361b550dcacd7d33d9d87dbd9498412625`
- Protected-head commit verification: `verified=true`, reason `valid`
- Catalog SHA-256 before this remediation:
  `c6022dbc31377fd7516e9a0676729845e24e4891c6f8b0f5c8985f8aad2e63ca`
- Candidate-template SHA-256:
  `2f77b38536a5b84b54c2bdcd63b4878db3fb6df994289eafe85ae44f108f33fc`
- Production-source-lock SHA-256:
  `bb8b9dac23fe71bd05baa9a01845f27dfd94e6e967e8e769e5cde9c4a1e2865c`
- Production release-tuple SHA-256:
  `f665eeece88664f05c73b731421866789d5de48cb5165f5c534d05836a192092`
- Evidence collection used repository metadata, protected-branch records,
  exact-head check runs, repository contracts, and release artifacts through
  the GitHub API. It did not contact Server A or Server B.

All 12 observed repository IDs match the stable IDs in the protected catalog,
and all 12 observed head commits report valid GitHub verification. Those facts
do not clear the contract, branch-protection, artifact, recovery, or runtime
gates below.

## Exact catalog blockers

| Order | Repository and observed head | Repository gate | Exact missing or contradictory evidence | Responsible role |
| ---: | --- | --- | --- | --- |
| 10 | `appolon1908-hue/Infustruction-repo` `4477415987a9e8067b5fdaaf335a3afcd4e8bc19` | **BLOCKED** | Protected branch exists and binds `validate-source` and `validate-merge-result`, but `.codestra/production-orchestrator-contract.v1.json` is absent at the exact head. No finalized `codestra.release-control.v1` runtime candidate exists; only `operations/staging-readonly/release-control.template.json` was found. | Infrastructure repository owner and runtime release authority |
| 20 | `appolon1908-hue/Keycloak` `dee685730f209c967325052fd9258e29d3ae96d7` | **BLOCKED** | Contract exists at SHA-256 `4481e7066a98668ea3a27f161f38a84f7606656efe5a7d212de8fd0c9a5e843f` and requires `validate`, but branch protection binds no required check. A passing check with another name does not satisfy the contract. | Identity repository owner and repository administrator |
| 30 | `appolon1908-hue/Middleware-` `4668de7d7ddc6f98968c06b7dc02d7650ff5e88a` | **BLOCKED** | Protected catalog role is `canonical-middleware`; exact-head contract SHA-256 `4d3b076d3fb99fa91ca16bd4cf56c3bdc658316f401f45abdf8b571bc37b0e4b` declares `transitional-middleware`, `deployment_authority=false`, and plan-only support. The contract must be reconciled through that repository's protected process; the catalog must not be reverted to the legacy authority. | Canonical Middleware owner and platform release-authority owner |
| 40 | `appolon1908-hue/codestra` `b3ecae9c535c2c6542aaa61b3c1cfa5d218d037b` | **BLOCKED** | Default branch is unprotected and the required repository contract is absent. | Application owner and repository administrator |
| 41 | `appolon1908-hue/beyvra-backend` `6a530bc0eb63dc382edf897ba6d09c34831e8bd5` | **BLOCKED** | Branch is protected, but the required repository contract is absent. | Application owner |
| 42 | `appolon1908-hue/backend2` `10a1e5fa21d0fa10b037c98807d7aa63c06619fb` | **BLOCKED** | Default branch is unprotected and the required repository contract is absent. | Application owner and repository administrator |
| 43 | `appolon1908-hue/beyvra-frontend` `46472a1e780f20c531297c74b1ab603156abea93` | **BLOCKED** | Branch is protected, but the required repository contract is absent. | Application owner |
| 44 | `appolon1908-hue/scrapper` `120528e1ac2d4f4ee200bfc4858bfde4e838ce8c` | **BLOCKED** | Migration-evidence repository is unprotected and its required plan-only, non-deployment-authority contract is absent. | Migration-evidence owner and repository administrator |
| 45 | `appolon1908-hue/Breero.com` `a5fc9921cbd6b71f83f1660fc505f02316572256` | **BLOCKED** | Branch is protected but binds no required check, and the required repository contract is absent. | Application owner and repository administrator |
| 46 | `appolon1908-hue/Moneybee-Backend` `ee03b38aab6780ea5692bcc2844545af4b2b9836` | **BLOCKED** | Branch has required checks, but the required repository contract is absent, so artifact counts, phase authority, safety controls, and contract-required checks cannot be authenticated. | Application owner |
| 47 | `appolon1908-hue/Telnexa-web` `e89ebfd78c8929b2c52e44fe7762cf415d8593fb` | **BLOCKED** | Default branch is unprotected and the required repository contract is absent. | Application owner and repository administrator |
| 90 | `appolon1908-hue/codestra-production-platform` `b5d574361b550dcacd7d33d9d87dbd9498412625` | **BLOCKED** | Contract exists at SHA-256 `d23a708fc026cf8416b86689bbe56d88dec2309daa1e2dbfb2606c1b36f907ef`, preserves `deployment_authority=false` and plan-only support, and branch protection expects `validate` from GitHub Actions app ID `15368`. No successful `validate` check exists on this exact protected head. | Controller repository owner |

Nine of the twelve catalog repositories therefore lack the required contract at
their observed protected/default head. Four default branches are unprotected.
The candidate cannot establish exact required-check sets or artifact policies
for repositories whose contracts are missing.

## Middleware signed-evidence audit

The current Appolon Middleware protected head has a non-expired signed release
bundle from run `34173524024`:

```text
artifact=signed-middleware-release-4668de7d7ddc6f98968c06b7dc02d7650ff5e88a-34173524024-1
artifact_digest=sha256:0a678bdb2d8796bb2d09d3203bb92a5eefeac447c76e49156917c5e5c5bf7adf
source_sha=4668de7d7ddc6f98968c06b7dc02d7650ff5e88a
image=ghcr.io/appolon1908-hue/codestra-middleware@sha256:41ae78d368b5e2db2e9fe9be50fd5041b3f1a07ae4837170a76a68889be565e6
migration_head=0057_platform_service_catalog
sbom_sha256=2ab69f32336a37b4f44990b31b108e3be79eea2c938e4b8079d3446f253b3a8a
vulnerability_report_sha256=3d1d22286c66070a2a6215f7768092af40e98ef2dc8db1a6ff7936322c9622c2
release_manifest_sha256=64564dfb72fea44a14e24dddbdfbfb069d7c1543b1005575a5a0d89ccb8a4232
sigstore_bundle_sha256=2f8a0de014a06d5a3c4b522de8a28e8a422a19877d23124d43da4fc1fe3eadd4
```

Read-only verification results:

- Manifest Sigstore bundle: **PASS** with exact workflow identity
  `https://github.com/appolon1908-hue/Middleware-/.github/workflows/release.yml@refs/heads/main`
  and OIDC issuer `https://token.actions.githubusercontent.com`.
- Image signature: **PASS** for the exact digest and workflow identity.
- SLSA provenance attestation: **PASS**; subject digest, source SHA
  `4668de7d7ddc6f98968c06b7dc02d7650ff5e88a`, and builder identity agree.
- SPDX 2.3 SBOM: **HASH PASS**, 96 packages and 2,289 files.
- Grype evidence: **HASH PASS**, zero recorded matches under the release policy.
- Platform signed-release verifier: **FAIL** because it certifies migration head
  `0056_klyrow_delivery_events`, while the exact-head manifest records
  `0057_platform_service_catalog`.

This bundle is not entered into a portfolio candidate. The protected platform
source lock still selects the older Appolon tuple
`63b6c0c8bca5168a1178895bd12858d0b1e8086e` /
`sha256:bca7a220b9ce50411ae67e2115507329656c4ee351333d14568af3695e3c347a`
at migration `0056_klyrow_delivery_events`. The latest exact-head release also
lacks a complete, separately verified previous-release rollback image set for
the portfolio candidate. The Middleware repository owner and platform
release-authority owner must reconcile the contract role, migration evidence,
source lock, verifier, and rollback identity as one protected change.

## Runtime candidate, images, and recovery

- No reviewed runtime candidate with schema `codestra.release-control.v1` was
  found at Infrastructure head
  `4477415987a9e8067b5fdaaf335a3afcd4e8bc19`; only a placeholder template was
  found. Therefore `runtime_candidate_sha256` is unavailable.
- `PRODUCTION-IMMUTABLE-CANDIDATE-MATRIX.yaml` is dated 2026-09-01, contains
  prior source lineages including `Codestra-SRL/codestra-middleware`, and is not
  an exact runtime candidate for the current 12-repository catalog.
- Complete immutable candidate and same-name previous-release image sets are
  unavailable for the exact current catalog heads. Signature, provenance, SBOM,
  and vulnerability evidence cannot be declared complete for the portfolio.
- The platform source lock has `status: FAIL`,
  `production_certified: false`, `deployment_authorized: false`, and records
  incomplete current staging, API/gateway, recovery, rollback, canary, and soak
  evidence.
- Infrastructure `STAGE7-ROLLBACK-EVIDENCE.md` records `ROLLBACK=FAIL`,
  `ROLLBACK_EXECUTED=NO`, and `RTO=NOT_MEASURED`. Repository CI was not treated
  as restore, rollback, or forward-recovery proof.

Responsible roles: infrastructure runtime authority for the exact runtime
candidate and complete rollback set; component release owners for immutable
images and supply-chain evidence; recovery owner for independent backup,
restore, forward-recovery, rollback, RPO and RTO evidence.

## Controller binding and plan-input status

The candidate cannot embed the commit hash that introduces its own file. The
reconciled policy uses `controller_sha` and the controller component
`source_sha` as the reviewed controller policy-base commit. At plan time the
workflow must independently prove that:

1. its workflow commit is the current protected controller head;
2. the candidate bytes are read from that exact workflow commit;
3. the recorded controller policy base is an ancestor of that head;
4. the controller contract hash matches the contract at the exact workflow
   head; and
5. the required `validate` check succeeded on that exact head from app ID
   `15368`.

This removes the impossible self-reference without weakening exact-head
validation.

Exact plan inputs cannot be prepared before a candidate exists and receives
review. The only invariant input currently known is:

```text
phase=plan
candidate_path=NOT_AVAILABLE
candidate_sha256=NOT_AVAILABLE
confirmation=PLAN_PORTFOLIO_RELEASE
observation_minutes=NOT_APPLICABLE_UNTIL_CANDIDATE_REVIEW
```

No release workflow was dispatched by this preparation.
