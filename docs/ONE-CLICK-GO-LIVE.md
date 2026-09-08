# One-click Codestra read-only go-live

## Operator button

After this workflow is merged into the protected release branch, open:

`https://github.com/appolon1908-hue/codestra-production-platform/actions/workflows/one-click-go-live.yml`

Choose **Run workflow**, retain `GO_LIVE_READONLY`, and keep the canary at `1` or lower.

This button does not bypass reviews, required checks, protected GitHub environments, signed-artifact verification, staging certification, backup/restore requirements, rollback rehearsal, or the production canary limit.

## What one click does

The platform wrapper performs one fail-closed sequence:

1. Verify that the exact checked-out `release/production-activation` SHA is still the protected branch head.
2. Require `PRODUCTION-SOURCE-LOCK.yaml` to be `PASS`, contain no blockers, and agree with `config/production-release-tuple.json`.
3. Require every custom candidate recorded in the source lock to be deployment-authorized.
4. Verify the canonical `appolon1908-hue/Middleware-` source has every
   catalog- and branch-required check successful on the exact protected head
   from the bound GitHub Actions app.
5. Reuse a checksummed successful `exact-main-production-release.yml` artifact for the exact source and digest, or dispatch that existing signed-release workflow when a new build is genuinely required.
6. Dispatch `appolon1908-hue/Infustruction-repo/.github/workflows/one-click-go-live.yml`.
7. Wait for isolated exact-digest staging, recovery-point creation, rollback rehearsal, and a production **GET/HEAD-only canary no greater than 1%**.
8. Publish the exact platform SHA, Middleware source SHA, digest, change ID, and canary percentage in the run summary.

The wrapper intentionally does **not** call `enable-production-web-traffic`. Successful completion means that the bounded read-only production canary is live, not that unrestricted traffic or business effects are enabled.

## Required protected configuration

Create the following secret in `appolon1908-hue/codestra-production-platform`:

### `CODESTRA_RELEASE_ORCHESTRATOR_TOKEN`

Use a fine-grained token or GitHub App installation token that can:

- read repository content and workflow runs in `appolon1908-hue/Middleware-`;
- dispatch and read Actions in `appolon1908-hue/Middleware-`;
- dispatch and read Actions in `appolon1908-hue/Infustruction-repo`.

Do not grant administration, secrets-write, ruleset-write, branch-delete, or force-push permissions.

### `CODESTRA_MIDDLEWARE_RELEASE_REQUEST_B64`

This is required only when no successful unexpired signed Middleware release artifact already matches the locked source SHA and digest. Its decoded value must be canonical compact JSON with exactly these fields:

```json
{"authority_artifact":"security-owner-authority-RUN-ATTEMPT","authority_document_sha256":"64-lowercase-hex","authority_run_id":123,"merged_pr_number":456,"source_sha":"40-lowercase-hex","vex_artifact":"production-openvex-SOURCE_SHA-RUN-ATTEMPT","vex_run_id":789}
```

The existing Middleware release workflow independently revalidates the merged PR, exact approval, required CI, Security Owner authority, OpenVEX, source SHA, image digest, SBOM, vulnerability policy, signature, and provenance.

## Infrastructure prerequisites

The child infrastructure repository must have:

- the protected `staging-readonly` environment and its exact candidate, endpoint, bearer, metrics, GHCR, and Restic bindings;
- the protected `production-readonly-canary` environment and its separate production bindings;
- a self-hosted runner labeled `codestra-staging`;
- a self-hosted runner labeled `codestra-production-canary`;
- the exact source/digest candidate and prior-release tuple required for rollback.

Missing configuration fails the run before promotion.

## Current gate

`PRODUCTION-SOURCE-LOCK.yaml` remains `FAIL`. Therefore the button is installed
for review, but it cannot deploy until the Appolon canonical Middleware
contract agrees with the protected catalog, every catalog repository has its
required protected contract and exact-head checks, complete immutable candidate
and rollback identities exist, and isolated staging and recovery evidence is
approved in the protected repositories.

## Effects that remain disabled

Successful one-click completion does not enable:

- live writes;
- live trading or money movement;
- payments or withdrawals;
- email or SMS delivery;
- PSTN dialing or callbacks;
- Odoo or n8n writes;
- unrestricted external-provider execution.
