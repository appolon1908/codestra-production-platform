# Codestra core production readiness report

Date: 2026-09-02
Production target: `65.109.65.169`
Staging target: `2.29.17.172`
Decision: **NO-GO**

## Verified progress

- Platform PR [#181](https://github.com/appolon1908-hue/codestra-production-platform/pull/181) merged through protected automation at `5aec485814149434750f2313370ae0ae39db5bd8`.
- Platform PR [#183](https://github.com/appolon1908-hue/codestra-production-platform/pull/183) established the fail-closed readiness artifacts at protected merge `b122da8d5ba51417c1887c2b796a2934f13ba1f9`.
- Platform PR [#185](https://github.com/appolon1908-hue/codestra-production-platform/pull/185) refreshed the Server 65 runtime count at protected merge `491041d5d0d66c4434470e8a03e5846a810f60ec`.
- Exact PR head `9cf4927f4019af71fc397b311a1f3d404d499b45` passed the required check.
- Platform release identity is supplied by the signed exact-release provenance generated after each protected merge; the source lock records its protected predecessor to avoid an impossible self-referential commit hash.
- Appolon Middleware source `f3437709c06747249586598590145234ea2c7327` and digest `sha256:a5c508fea8634351fb1bdd11e22a6cea520e436355cba3305456a07a3e0a2484` implement the three n8n API gaps, but are not deployed.
- Branch protections retain strict status checks, conversation resolution, admin enforcement, and force-push/deletion denial. No bypass was used.
- All dangerous external-effect switches remain disabled. No email, SMS, social post, advertisement, model request, payment, or PSTN call was initiated.
- Klyrow and Telnexa source-defined public health/readiness endpoints pass with authoritative DNS, exact peer, and TLS hostname verification; private mTLS/service-identity integration gates remain FAIL (`evidence/server65/PROVIDER-READONLY-HEALTH-20260902.md`).
- Provider credential read-back is fail-closed: Klyrow authority and consumer states disagree, Telnexa consumer validation fails despite an active declaration, and Kyqra is uninitialized (`evidence/server65/PROVIDER-CREDENTIAL-STATE-20260902.md`).
- All 24 known unpinned deployments were refreshed from safe live Docker metadata; none has a digest-pinned Compose reference, only four expose a valid repository/SHA pair, and four deployment authorities remain under inaccessible `/root` worktrees (`evidence/server65/SOURCE-AUTHORITY-24-DEPLOYMENTS-20260902.yaml`).
- The three required n8n gaps are reconciled without inflating the 641 runtime-derived record count: two absent contracts remain in the required-gap register and live Kong record `ep-0577` is the broken collection route (`evidence/server65/API-GAP-RECONCILIATION-20260902.yaml`).
- Canonical Middleware protected release CI is externally blocked before job creation: the `Codestra-SRL` organization Actions budget is zero and prevents further usage. No billing control was changed (`evidence/repository-review/CANONICAL-MIDDLEWARE-ACTIONS-BLOCKER-20260902.md`).
- The three n8n operation gaps are now implemented on canonical Middleware PR `Codestra-SRL/codestra-middleware#283` at signed head `e48ec614a2da680802ee106e271b52f3006e72dc`; local Ruff, MyPy, and all 1,261 repository tests pass. Exact-head CI and image publication remain blocked by the same Actions entitlement, so runtime gap count remains three and no deployment is authorized.
- Codestra AI protected source `7d31ef8de1c15bcc71b61de50917c81e3bcf557d` produced immutable candidate `ghcr.io/appolon1908-hue/codestra-ai@sha256:908c59e54a2620142e597523fa31b5d1d710dc00156b35c5a642e5437362df3e`; registry read-back confirms non-root execution and exact OCI source/revision/version/created labels. It is not deployed and does not change the AI gate from FAIL. Evidence: `evidence/server65/AI-MARKETING-IMMUTABLE-CANDIDATES-20260902.md`.
- Codestra Marketing protected source `fe784f1e91bb0f0fd49f2b2f741a4020a337c149` produced immutable candidate `ghcr.io/appolon1908-hue/codestra-marketing@sha256:3d9bd44922ad02d865f191cac5c9e454b88bb7cbfc8cd643f81e7b57f132c391`; registry read-back confirms non-root execution and exact OCI source/revision/version/created labels. It is not deployed and does not change the Marketing gate from FAIL. Evidence: `evidence/server65/AI-MARKETING-IMMUTABLE-CANDIDATES-20260902.md`.

## Runtime baseline

Running containers: 106 (refreshed after the initial 102-container baseline)
Live Kong routes: 29
Endpoint records: 641
Runtime OpenAPI applications: 20
Monitoring coverage: 2/20

The prior `4/20` numerator included one explicitly staging application and one
non-container Caddy proxy observation. The reconciled production denominator
contains 20 runtime applications, of which two expose explicit health,
readiness, and metrics contracts. See
`evidence/server65/OPENAPI-MONITORING-COVERAGE-20260902.yaml`.

The count change is not attributed to this remediation session; no container mutation was performed. See `evidence/server65/RUNTIME-REFRESH-20260902.md`.

## Mandatory gate matrix

| Gate | Result |
|---|---|
| REPOSITORY_AUTHORITY | FAIL |
| SOURCE_LOCK | FAIL |
| IMMUTABLE_IMAGES | FAIL |
| SIGNED_RELEASES | FAIL |
| SBOM | FAIL |
| PROVENANCE | FAIL |
| VULNERABILITY_GATE | FAIL |
| CADDY | FAIL — active and syntactically valid, but the approved health gate returns 503 for `api.breero.com`; readiness/version, exact source alignment, and structural secret-redaction proof remain failed (`evidence/server65/CADDY-RUNTIME-READBACK-20260902.md`) |
| KEYCLOAK | FAIL — public discovery, issuer, JWKS, TLS, and advertised S256 read-back pass; authenticated client, audience, tenant, MFA, service-account, and session controls remain uncertified (`evidence/server65/KEYCLOAK-RUNTIME-READBACK-20260902.md`) |
| KONG | FAIL — all 29 routes are inventoried, but the live 503 remains unattributed until the reviewed, sanitized `kong-readback` action is separately approved and installed; global traffic-gate state must be checked before an upstream is blamed (`evidence/server65/KONG-RUNTIME-READBACK-BLOCKER-20260902.md`) |
| MIDDLEWARE | FAIL |
| ODOO | FAIL |
| N8N | FAIL |
| MARKETING | FAIL |
| AI | FAIL |
| COMMUNICATION | FAIL |
| SOCIAL | FAIL |
| PROVISIONING | FAIL |
| OPENBAO | FAIL |
| SECRET_INJECTION | FAIL |
| SERVICE_CREDENTIAL_ISOLATION | FAIL |
| POSTGRES_PRIVATE | FAIL |
| REDIS_PRIVATE | FAIL |
| DATABASE_ROLE_ISOLATION | FAIL |
| ONE_SHOT_MIGRATIONS | FAIL |
| DATABASE_BACKUPS | FAIL |
| OFF_HOST_BACKUPS | FAIL |
| RESTORE_TEST | FAIL |
| RPO | FAIL |
| RTO | FAIL |
| HEALTH_ENDPOINTS | FAIL |
| READINESS_ENDPOINTS | FAIL |
| VERSION_ENDPOINTS | FAIL |
| CAPABILITY_ENDPOINTS | FAIL |
| OPENAPI_CONTRACTS | FAIL |
| AUTHENTICATION | FAIL |
| AUTHORIZATION | FAIL |
| TENANT_ISOLATION | FAIL |
| IDEMPOTENCY | FAIL |
| INBOX | FAIL |
| OUTBOX | FAIL |
| WEBHOOK_SECURITY | FAIL |
| RETRY_POLICY | FAIL |
| DEAD_LETTER | FAIL |
| CIRCUIT_BREAKERS | FAIL |
| AUDIT_TRAIL | FAIL |
| METRICS | FAIL |
| LOGS | FAIL |
| TRACES | FAIL |
| ALERTS | FAIL |
| ON_CALL_OWNERSHIP | FAIL |
| STAGING_ISOLATED | FAIL |
| STAGING_CERTIFICATION | FAIL |
| EXACT_DIGEST_PROMOTION | FAIL |
| PRODUCTION_READ_ONLY_CANARY | FAIL |
| ROLLBACK | FAIL |
| DOCKER_SOCKET_PROTECTED | FAIL |
| SSH_UNCHANGED | PASS — `evidence/server65/READONLY-SAFETY-ATTESTATION.md` |
| EXTERNAL_EFFECTS_FAIL_CLOSED | PASS — `evidence/server65/READONLY-SAFETY-ATTESTATION.md` and `PRODUCTION-CAPABILITY-MATRIX.yaml` |

## Blocking authority mismatch

The protected production activation tuple authorizes `Codestra-SRL/codestra-middleware` at source `f199b6c40f4e467979e9a8b255a0e686321a182d`, digest `sha256:ec2cf4ca73ff072fbdd48bda108a60f103526cb3e97a721abdf38435b010908b`, and migration `0056_klyrow_delivery_events`. PR #181 records a distinct Appolon implementation at migration `0006_outbox_attempt_events`. Activation workflow run `33641517234` rejected the requested tuple before server access. Substituting one authority for the other would violate source and migration gates.

## External capabilities

Enabled: none.
Disabled: email delivery, SMS delivery, PSTN dialing, social publishing, advertising, external model calls, and n8n external-provider writes.

OVERALL_VERDICT=PRODUCTION_BLOCKED
