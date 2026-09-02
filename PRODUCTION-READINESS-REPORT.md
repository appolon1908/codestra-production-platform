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
- Latest protected platform release `protected-491041d5d0d66c4434470e8a03e5846a810f60ec` passed complete source tests, SBOM/provenance generation, signature verification, and immutable publication.
- Appolon Middleware source `f3437709c06747249586598590145234ea2c7327` and digest `sha256:a5c508fea8634351fb1bdd11e22a6cea520e436355cba3305456a07a3e0a2484` implement the three n8n API gaps, but are not deployed.
- Branch protections retain strict status checks, conversation resolution, admin enforcement, and force-push/deletion denial. No bypass was used.
- All dangerous external-effect switches remain disabled. No email, SMS, social post, advertisement, model request, payment, or PSTN call was initiated.

## Runtime baseline

Running containers: 106 (refreshed after the initial 102-container baseline)
Live Kong routes: 29
Endpoint records: 641
Runtime OpenAPI applications: 20
Monitoring coverage: 4/20

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
| CADDY | FAIL |
| KEYCLOAK | FAIL |
| KONG | FAIL |
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
