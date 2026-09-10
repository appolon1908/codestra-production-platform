# Calling release read-back API

`GET /v1/admin/system/calling-readiness` implements a read-only comparison for
issues #257, #258, #259 and #262. It uses the existing platform-admin authentication
and Kong `/v1/admin/system` policy. Anonymous, tenant-admin, and auditor requests
receive 403. Query parameters receive 400; callers cannot select files or hosts.
The API assurance inventory retains the existing gateway gap: Kong currently
requires a tenant claim even for global platform administrators. The direct HTTP
authorization tests do not certify this public gateway path.

HTTP 200 / `READBACK_MATCHES` means the supplied evidence matches the expected
readonly release. HTTP 503 / `BLOCKED` includes stable component/code blockers.
Both return `production_activation_authorized: false` and
`live_state_collected: false`. This is not full production certification.
The endpoint performs no outbound requests, writes, deployment, or dialing.

## Evidence authority and installation

The deployment authority must independently verify protected merges, signatures,
provenance, runtime identities, backup/restore and rollback before collecting
these assertions. This evaluator does not cryptographically verify those proofs.
It trusts its mounted files. Do not accept uploads or let API consumers write them.
Keep the reviewed expected tuple separate from the runtime collector's output;
the collector must not be able to change expected release identities.

Configure `CALLING_EXPECTED_EVIDENCE_FILE` and `CALLING_OBSERVED_EVIDENCE_FILE`,
or combine `deploy/control-plane/calling-readiness.override.yaml` with the reviewed
deployment manifest. The overlay requires existing `CALLING_RELEASE_DIRECTORY`
and `CALLING_READBACK_DIRECTORY`, mounting both read-only. Each directory must be
operator-owned and readable by service UID 10001. Publish files atomically as
`expected.json` and `observed.json`. Directory mounts preserve atomic replacement
visibility. No service restart or public port is required for evidence refresh.
Missing files fail closed. Each JSON document is limited to 1 MiB; duplicate keys,
invalid UTF-8, malformed JSON, and non-object roots are rejected without reflecting
file paths or contents into API responses.

## Input format: calling-evidence.v1

Both documents contain `schema_version: calling-evidence.v1`, `environment`
(`staging-readonly` or `production-readonly`), `contract_digest` (prefixed
`sha256:`), `release_digest`, and `components`.

The component keys are exactly `platform`, `middleware`, `vicidial`, `websocket`,
`odoo`, `caddy`, `kong`, `keycloak`, `sdk`, `infrastructure`, `n8n`, `operator_ui`.
Their repository names follow the parent mission's Appolon authorities. Each
expected component contains:

| Field | Value |
| --- | --- |
| repository | Exact `appolon1908-hue/<owning-repository>` |
| repository_id | Positive integer stable GitHub repository ID |
| protected_branch | Reviewed branch name |
| source_sha | Protected merge SHA, 40 lowercase hex characters |
| artifact_digest | Immutable image or source-bundle `sha256:` digest |
| configuration_digest | Reviewed configuration `sha256:` digest |
| rollback_digest | Previous immutable artifact `sha256:` digest |
| migration_head | Exact migration identity, or explicit `not-applicable` |
| runtime_identity | Verified host/service identity or installed artifact identity |

Compute `release_digest` as SHA-256 of UTF-8 JSON of the entire expected document,
excluding only its top-level `release_digest`: sorted keys, compact separators,
no NaN, Python's default ASCII escaping. The exported `release_digest(document)`
function implements this format. Proofs bind to this digest, so changing any
expected tuple field invalidates prior proof references.

Each observed component repeats those exact fields and adds `contract_digest`,
timezone-aware ISO-8601 `captured_at`, and literal JSON `true` for `healthy`,
`ready`, `signature_verified`, `provenance_verified`, `protected_merge_verified`.
Artifact-only components report verified installed-artifact checks, not invented
service probes. The top-level observed document adds `captured_at`; every component
timestamp must be no later than it. All observations must be within 300 seconds of
evaluation, with no future timestamps. Refreshing just the outer timestamp cannot
make stale component observations pass.

Observed `safety` requires:

- Literal `false` for `VICIDIAL_WRITES`, `LIVE_CALL_CONTROL`, `PRODUCTION_DIALING`,
  `LIVE_PSTN_DIALING`, `TELEPHONY_ADMIN_WRITE`, and every operational action flag:
  `ENABLE_VICIDIAL_WRITES`, `ENABLE_CAMPAIGN_SYNC`, `ENABLE_AGENT_SYNC`,
  `ENABLE_AGENT_PROVISIONING`, `ENABLE_INTERNAL_TEST_CALLING`,
  `ENABLE_LEAD_PUBLICATION`, `ENABLE_LIVE_CALL_CONTROL`, `ENABLE_WARM_TRANSFER`,
  `ENABLE_IVR_ROUTING`, `ENABLE_IVR_CALLBACKS`, `ENABLE_APPT_PREP`,
  `ENABLE_PROVISIONING`, `ENABLE_PRODUCTION_DIALING`, `ENABLE_EMAIL_DELIVERY`,
  `ENABLE_SMS_DELIVERY`, `ENABLE_AI_ACTIONS`, `SEND_EVENTS`,
  `ENABLE_EXTERNAL_DELIVERY`, `LIVE_WRITE`, `ODOO_WRITE`, `N8N_DELIVERY_ENABLED`,
  `GENERAL_AI_DIALING`, `CALLBACK_DISPATCH`. Every field must be present;
  collectors normalize source values such as `DISABLED` to JSON `false` only
  after authoritative read-back. Missing values are not disabled evidence.
- Integer zero for `calls_placed_before`, `calls_placed_after`, `unexpected_writes`,
  `event_lag_seconds`, `reconciliation_depth`. These are counters for the named
  readonly certification window; do not reset lifetime provider counters.
- Integer one for `middleware_authority_count`.
- Literal `true` for `asterisk_ready`, `ami_ready`, `trunk_ready`,
  `mtls_identity_verified`, `callback_signature_verified`,
  `callback_replay_protection_verified`.

Observed `proofs` contains `backup`, `restore`, `rollback`, `monitoring`, `identity`,
`route_policy`. Each requires `passed: true`, the matching `contract_digest` and
`release_digest`, plus the retained proof's `evidence_digest` (`sha256:`).
The deployment authority remains responsible for proof authenticity and retention.

Observed `server_b` is also required. Its complete contract is documented in
[`SERVER_B_CALLING_READINESS.md`](SERVER_B_CALLING_READINESS.md), including the
read-only profile, runtime/queue/health checks, and durable call counters.

## Publishing collector observations

`control_plane_service.calling_evidence` publishes a collector's recorded
`calling-evidence.v1` document atomically. It uses the evaluator's `FLAGS`
definition, so the producer requires the same fields, including
`ENABLE_AGENT_PROVISIONING` and `ENABLE_INTERNAL_TEST_CALLING`. Read both from
the canonical adapter's effective runtime configuration; never infer them from
`writes_enabled`. Missing fields are rejected. An explicitly unavailable
observation may be JSON `null`, which the readiness evaluator blocks.

The collector must supply `server_b`, all required safety observations, and
the other recorded evidence. The publisher normalizes explicit `false`/`DISABLED`
and `true`/`ENABLED` strings. It preserves unknowns, enabled flags, collection
timestamps, identities, counters, and proofs. It does not collect live state or
turn a published document into successful certification.

```bash
python3 -m control_plane_service.calling_evidence \
  --readback /protected/collector/calling-readback.json \
  --output /run/calling-readback/observed.json
```

The existing destination directory must be operator-owned, with its setgid
group readable by service UID 10001, so the atomic replacement inherits the
approved group. Output files use mode 0640. Invalid input leaves the previous
file untouched; its original timestamps still expire normally. Publication
does not change the separate expected release file.

## CLI and tests

Run the same evaluator without starting the HTTP service:

```bash
python3 -m control_plane_service.calling_readiness \
  --expected /run/calling-release/expected.json \
  --observed /run/calling-readback/observed.json
```

Exit 0 means `READBACK_MATCHES`; exit 1 means blocked. There is no activation mode.
Synthetic fixtures in `tests/test_calling_readiness.py` illustrate the complete
input structure; they are test data and must never be deployed as runtime evidence.

```bash
python3 -m pytest -q tests/test_calling_readiness.py tests/test_system_health_contract.py
```

Production rollout, real evidence collection, cross-repository runtime changes,
secret injection, PSTN canaries, and closure of the mission issues remain separate
work. This implementation does not claim those tasks have passed.
