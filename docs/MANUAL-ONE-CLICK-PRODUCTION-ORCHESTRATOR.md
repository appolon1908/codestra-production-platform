# Manual one-click protected production orchestrator

## What “one click” means

The operator starts one `workflow_dispatch` from the protected
`release/production-activation` branch. The workflow then executes a fixed,
evidence-bound train:

1. portfolio plan and exact-head verification;
2. protected staging release intents;
3. immutable staging deployment and certification;
4. rollback rehearsal and candidate restoration;
5. protected one-percent GET/HEAD-only production canary;
6. a bounded observation window;
7. protected promotion of the same candidate to 100 percent traffic.

“One click” does not remove review. Jobs pause independently at the protected
environments `portfolio-release-plan`, `portfolio-staging`,
`portfolio-production-canary`, and `portfolio-production`.

## Portfolio authority

The catalog contains these required repositories:

- `appolon1908-hue/Infustruction-repo`
- `appolon1908-hue/Keycloak`
- `Codestra-SRL/codestra-middleware`
- `appolon1908-hue/Middleware-`
- `appolon1908-hue/codestra`
- `appolon1908-hue/beyvra-backend`
- `appolon1908-hue/backend2`
- `appolon1908-hue/beyvra-frontend`
- `appolon1908-hue/scrapper`
- `appolon1908-hue/Breero.com`
- `appolon1908-hue/Moneybee-Backend`
- `appolon1908-hue/Telnexa-web`
- `appolon1908-hue/codestra-production-platform`

Every repository is bound by stable GitHub repository ID, exact default branch,
exact source SHA, a versioned repository-owned contract, required checks, and
immutable candidate/rollback image identities.

`Codestra-SRL/codestra-middleware` remains the canonical Middleware authority.
`appolon1908-hue/Middleware-` is present for required source/evidence
verification but its contract must remain non-deployment-authoritative until a
separate protected authority migration changes that decision. Likewise,
`appolon1908-hue/scrapper` remains migration evidence only while
`kyqra-crawler` owns crawler production deployment.

## Repository release contract

Each catalog repository must merge both:

```text
.codestra/production-orchestrator-contract.v1.json
.github/workflows/manual-release-intent.yml
```

The normalized manual release-intent workflow:

- runs only from the exact protected default-branch head;
- verifies stable repository ID;
- combines branch-protection checks with contract-required checks;
- accepts only `image@sha256:...` identities;
- requires a distinct complete rollback image set;
- forbids rebuild and retag after staging;
- produces a normalized JSON intent artifact;
- pauses at `staging-readonly`, `production-readonly-canary`, or `production`;
- never contacts a runtime or changes production itself.

The central controller consumes the intent artifacts. Runtime mutation remains
inside the infrastructure release controller.

## Candidate preparation

Copy:

```text
config/manual-production-candidate.template.v1.json
```

to:

```text
config/releases/<release-id>.json
```

Then replace every placeholder with reviewed evidence:

- `template=false`;
- one release ID;
- the controller authority SHA;
- one exact passing source-lock SHA;
- SHA-256 of the protected `codestra.release-control.v1` runtime candidate;
- each repository’s exact protected branch head;
- SHA-256 of each repository contract;
- complete candidate `image@sha256` identities;
- complete previous-release `image@sha256` identities.

The file must retain:

```text
canary_percent=1
production_percent=100
allowed_canary_methods=GET,HEAD
external_effects_enabled=false
live_email_delivery=false
live_sms_delivery=false
live_pstn_dialing=false
odoo_write=false
n8n_external_delivery=false
live_trading=false
payment_execution=false
```

Compute its exact hash:

```bash
sha256sum config/releases/<release-id>.json
```

A candidate is rejected if a source branch moved, a repository ID changed, a
contract hash changed, a required check is missing or not successful, a mutable
tag is present, a rollback image equals the candidate image, or a required
repository is omitted.

## Manual dispatch confirmations

| Highest phase | Confirmation |
|---|---|
| `plan` | `PLAN_PORTFOLIO_RELEASE` |
| `staging` | `DEPLOY_PORTFOLIO_STAGING` |
| `canary` | `START_PORTFOLIO_READONLY_CANARY` |
| `production` | `PROMOTE_PORTFOLIO_TO_100_PERCENT` |

A production dispatch still pauses for every environment gate and executes all
earlier phases. It cannot jump directly to production.

## Controller token

Each of the four controller environments needs an encrypted secret named:

```text
CODESTRA_ORCHESTRATOR_TOKEN
```

Use a fine-grained token or GitHub App installation token with only the
repositories in the catalog and these repository permissions:

```text
Actions: read and write
Checks: read
Contents: read
Metadata: read
```

The token must also be installed for the organization-owned
`Codestra-SRL/codestra-middleware` repository. Do not grant repository
administration, secret write, branch write, package delete, or environment
bypass permission to the orchestration token.

## Infrastructure authority

`appolon1908-hue/Infustruction-repo` remains the runtime authority. The central
workflow dispatches its protected
`.github/workflows/staging-readonly-certification.yml` for:

```text
mode=staging
mode=rollback-rehearsal
mode=production-readonly-canary
```

That workflow already performs digest-only pulls, OCI source readback, backups,
off-host recovery evidence, isolated restore, 29-route Kong checks, Keycloak
issuer checks, readiness, protected metrics, zero-effect counters, rollback,
and a maximum one-percent GET/HEAD-only canary.

The infrastructure workflow must be updated so rollback rehearsal authenticates
the exact staging run and canary authenticates both the exact staging and exact
rollback-rehearsal artifacts. The final production stage uses the separately
protected `production-traffic-promotion.yml`; it must authenticate staging,
rollback, canary, and observation evidence before invoking a fixed,
checksummed traffic controller.

## Canonical Middleware unblock

The canonical `Codestra-SRL/codestra-middleware` contract requires
`codestra/required-ci` on the exact source head. The controller never fabricates
or manually posts that status.

The repository must provide a `workflow_dispatch` exact-head CI path that runs
inside `Codestra-SRL/codestra-middleware` and therefore produces the required
GitHub Actions check from the correct app. The source SHA, tests, image digest,
SBOM/provenance, and signed release evidence must all match before its release
intent can pass.

An account billing or Actions-usage block is not converted to PASS. It remains
an external blocker until GitHub permits the required workflow to create and
complete its jobs.

## Full-traffic boundary

A successful one-percent canary does not enable external effects. The 100%
traffic promotion uses the same immutable images and source SHAs but retains
all external-effect controls disabled.

Email, SMS, PSTN, advertising, social publication, Odoo writes, n8n provider
delivery, payments, trading, and other effectful capabilities require separate
activation candidates, evidence, approvals, and rollback controls.

## Fail-closed conditions

The controller stops on any:

- source, contract, repository-ID, image, or evidence mismatch;
- unprotected default branch;
- missing, stale, skipped, neutral, cancelled, or failed required check;
- missing protected environment approval;
- missing release-intent artifact;
- missing staging, rollback, canary, or observation evidence;
- mutable image tag, rebuild, or retag;
- staging or rollback failure;
- canary above one percent or method outside GET/HEAD;
- readiness, identity, route, metrics, backup, restore, or monitoring failure;
- unexpected write or live-effect counter movement;
- 100% promotion that does not use the exact canary candidate.

No administrative bypass path is part of this design.
