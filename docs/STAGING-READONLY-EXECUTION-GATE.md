# Codestra staging-readonly execution gate

## Purpose

This contract controls the path from an immutable repository candidate to an
isolated staging deployment, complete read-only certification, paired recovery
evidence, rollback rehearsal, and a production read-only canary capped at one
percent.

Repository preparation is not deployment authorization. The workflow must stop
before SSH whenever any source, artifact, infrastructure, environment, endpoint,
identity, backup, rollback, observability, or live-effect condition is missing or
contradictory.

## Current entry-gate result

```text
STAGING_READONLY_GATE=BLOCKED
PRODUCTION_SOURCE_LOCK=FAIL
RUNTIME_CANDIDATE_DEPLOYMENT_AUTHORIZED=false
STAGING_HOST_STATUS=NOT_RUN_HOST_NOT_CREATED
STAGING_ENVIRONMENT_CONFIGURATION=NOT_VERIFIED
STAGING_DEPLOYMENT=NOT_RUN
PRODUCTION_CANARY=NOT_RUN
PRODUCTION_CHANGED=false
```

The authoritative machine-readable result is
`evidence/staging-readonly/entry-gate-2026-09-03.json`.

## GitHub environment

Create or configure the repository environment named exactly
`staging-readonly`. Limit deployment branches to
`release/production-activation`; do not allow arbitrary branches or tags to
consume its credentials. The environment must contain only read-only staging
identity, registry-read, backup-transfer, and verification material. It must not
contain a production write token, provider credential, Odoo write credential,
n8n activation credential, SMTP credential, SMS credential, telephony
credential, payment credential, or trading credential.

### Required environment variables

| Variable | Contract |
|---|---|
| `CODESTRA_STAGING_OPERATOR_HOST` | Verified isolated staging host only; hostname or IP without scheme, path, or embedded credentials. |
| `CODESTRA_STAGING_OPERATOR_USER` | Restricted forced-command staging operator; not `root`. |
| `CODESTRA_STAGING_OPERATOR_PORT` | Verified SSH port, integer 1-65535. |
| `CODESTRA_STAGING_CANDIDATE_ID` | Exact immutable release identity in the protected endpoint manifest. |
| `CODESTRA_STAGING_CANDIDATE_MANIFEST_SHA256` | SHA-256 of the complete cross-repository candidate manifest. |
| `CODESTRA_STAGING_ENDPOINT_MANIFEST_SHA256` | SHA-256 of the encrypted environment endpoint manifest after exact serialization. |
| `CODESTRA_STAGING_KEYCLOAK_ISSUER` | Credential-free HTTPS issuer expected from discovery and token validation. |
| `CODESTRA_STAGING_OFF_HOST_BACKUP_URI` | Credential-free `s3://` or `https://` destination on a failure domain separate from staging. |
| `CODESTRA_STAGING_CANARY_MAX_PERCENT` | Must be greater than zero and no more than `1`. |
| `CODESTRA_STAGING_KONG_ROUTE_COUNT` | Must be exactly `29`. |

### Required encrypted environment secrets

| Secret | Purpose |
|---|---|
| `CODESTRA_STAGING_READONLY_OPERATOR_SSH_KEY` | Restricted forced-command staging operator identity. |
| `CODESTRA_STAGING_READONLY_OPERATOR_KNOWN_HOSTS` | Exact host-key pin for the verified staging host. |
| `CODESTRA_GHCR_DEPLOYMENT_READ_TOKEN` | Registry pull only; no package write/delete permission. |
| `CODESTRA_STAGING_READONLY_ENDPOINT_MANIFEST` | Exact non-template JSON endpoint/candidate manifest. It contains no credential values. |
| `CODESTRA_STAGING_READONLY_BEARER_TOKEN` | Read-only application verification identity. |
| `CODESTRA_STAGING_METRICS_BEARER_TOKEN` | Read-only protected-metrics identity. |
| `CODESTRA_STAGING_OFF_HOST_BACKUP_CREDENTIAL` | Create-only or tightly scoped transfer credential for the approved off-host destination. |
| `CODESTRA_RELEASE_SIGNING_PUBLIC_KEY` | Verification material for immutable candidate signatures. |

The workflow tests only the presence of encrypted secrets and never writes their
values to logs or artifacts.

## Protected endpoint manifest

Use `config/staging-readonly-endpoint-manifest.template.v1.json` as a schema
example. Store the completed JSON in
`CODESTRA_STAGING_READONLY_ENDPOINT_MANIFEST` and its exact SHA-256 in
`CODESTRA_STAGING_ENDPOINT_MANIFEST_SHA256`.

The materialized manifest must:

1. set `template` to `false`;
2. bind one non-zero platform SHA and one non-zero source-lock checksum;
3. enumerate every deployed component with repository, exact source SHA,
   registry repository, and immutable OCI digest;
4. set `rebuild_allowed=false` and `retag_allowed=false` for every component;
5. enumerate the same component set for the previous rollback candidate;
6. define credential-free HTTPS health, readiness, version, capabilities, and
   protected-metrics paths;
7. enumerate exactly 29 Kong read-only smoke routes;
8. bind expected database migration heads;
9. require database, Odoo filestore, configuration, and off-host backups;
10. require positive RTO and RPO limits and post-rollback data-integrity,
    health, readiness, and version readback;
11. keep every governed live-effect capability false;
12. contain credential references only, never token, key, password, or secret
    values.

## Execution sequence

### Gate 0 — authority and environment preflight

Run `tools/validate_staging_readonly_authority.py --mode policy` in source CI.
The environment preflight writes the protected endpoint manifest to a
permission-0600 temporary file, verifies its SHA-256, validates variable and
secret presence, and validates all immutable candidate and safety conditions.

Any missing input or non-PASS authority blocks before SSH.

### Gate 1 — isolated staging deployment

Only after Gate 0 is `PASS`, the restricted staging operator may:

- pull exact `image@sha256:digest` references;
- verify signatures, attestations, source labels, and manifest checksums;
- verify the deployed source readback equals the candidate source SHA;
- use `--pull never` after the verified pull;
- prohibit build and retag operations;
- apply one-shot migrations separately from application startup;
- start all live-effect controls false;
- preserve the previous exact candidate for immediate rollback.

A source label or runtime digest mismatch stops the deployment and restores the
previous candidate.

### Gate 2 — staging read-only certification

Every required check must pass against the deployed candidate:

- source-version readback;
- health and readiness;
- fail-closed capability state;
- protected metrics;
- exact Keycloak issuer discovery;
- all 29 Kong read-only smoke routes;
- expected database migration heads;
- zero call delta;
- zero email delta;
- zero SMS delta;
- zero provider-effect delta;
- continuous monitoring visibility;
- latency and error-budget thresholds;
- denial of every governed write method.

The workflow must not invoke a webhook, submit a business command, place a call,
send a message, start a campaign, or perform an Odoo write while certifying.

### Gate 3 — paired backups and off-host copy

Create one release-bound recovery set containing:

- a consistent database backup;
- the matching Odoo filestore snapshot;
- the matching configuration, source-lock, candidate manifest, image-digest,
  migration-head, and checksum bundle.

Encrypt and checksum the recovery set, copy it to the approved off-host failure
domain, and verify the remote object checksum. A database backup without the
matching filestore and configuration bundle does not pass.

### Gate 4 — rollback rehearsal

From the exact staging candidate:

1. record the starting timestamp and current candidate readback;
2. switch to the previous exact source SHAs and image digests without rebuild or
   retag;
3. apply the documented database compatibility decision;
4. restore only when the rehearsal plan requires restoration;
5. verify data integrity, health, readiness, version, migration state,
   monitoring, and zero live-effect deltas;
6. record measured RTO and RPO;
7. return to the exact candidate and repeat all readbacks.

Both directions must pass. A one-way downgrade test is insufficient.

### Gate 5 — production read-only canary

Canary authorization is separate from staging deployment authorization. Promote
the same immutable component digests that passed staging and rollback; do not
rebuild or retag.

The production canary must:

- receive no more than one percent of traffic;
- accept only `GET` and `HEAD` verification requests;
- deny `POST`, `PUT`, `PATCH`, `DELETE`, `CONNECT`, and `TRACE`;
- retain every live-effect capability false;
- continuously compare source SHA, image digest, readiness, monitoring,
  migration state, latency, error rate, and live-effect counters;
- automatically return traffic to the previous candidate on any abort
  condition.

## Mandatory abort and rollback conditions

Stop immediately and roll back on any of the following:

- source SHA mismatch;
- image digest mismatch;
- readiness failure;
- monitoring loss;
- database migration drift;
- latency regression;
- error-rate regression;
- any write request reaching the candidate;
- movement in call, email, SMS, or provider-effect counters;
- backup, restore, checksum, or data-integrity failure.

## Live-effect boundary

These controls remain false throughout staging, rollback, and the production
read-only canary:

```text
LIVE_WRITE=false
ODOO_WRITE=false
ENABLE_EXTERNAL_DELIVERY=false
N8N_DELIVERY_ENABLED=false
LIVE_EMAIL_DELIVERY=false
LIVE_SMS_DELIVERY=false
LIVE_PSTN_DIALING=false
PRODUCTION_DIALING=false
CAMPAIGN_ACTIVATION=false
PROVIDER_DELIVERY=false
ADVERTISING_ACTIVATION=false
PAYMENT_EXECUTION=false
FINANCIAL_TRADING=false
```

Enabling any one of them requires a separate production-write activation
candidate, independent evidence, and a distinct protected change. Passing this
read-only sequence does not authorize live effects.
