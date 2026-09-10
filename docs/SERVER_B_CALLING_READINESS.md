# Server B calling-readiness evidence

Issue #259 owns certification of `65.21.67.207` / `10.40.0.2`. The canonical
adapter source remains `appolon1908-hue/Vicidialer-Codestra`; this platform
repository evaluates its release and runtime observations.

`control_plane_service.calling_readiness` now requires a `server_b` object in
the operator-mounted `CALLING_OBSERVED_EVIDENCE_FILE`. The existing
`GET /v1/admin/system/calling-readiness` route returns HTTP 503 with sanitized
`SERVER_B_*` reason codes when this evidence is missing or failing. Its
platform-admin authorization and release/proof validation still apply.

## Evidence contract

The deployment authority must collect actual observations, not populate this
object from expected values. Unavailable checks are null or omitted and block
readiness. This evaluator does not authenticate a supplied assertion, collect
live state, change a feature flag, authorize deployment, or certify production.

| Field | Required observation |
| --- | --- |
| `schema_version` | `server-b-readiness.v1` |
| `captured_at` | Timezone-aware timestamp, no older than 300 seconds and never in the future |
| `public_ip`, `private_ip` | Verified host identity, `65.21.67.207` and `10.40.0.2` |
| `source_sha`, `artifact_digest` | Deployed adapter identity, matching the expected canonical VICIdial release |
| `release_digest` | Complete expected calling release digest, also bound to the parent evidence/proofs |
| `deployment_profile` | `production-candidate`, the non-dialing profile with local MySQL read-back |
| Each `REQUIRED_CHECKS` field in `server_b_readiness.py` | JSON `true`, established by fresh authenticated read-back or verified recovery evidence for this release |
| Each `ZERO_COUNTERS` field | Explicit integer zero; unknown, negative, boolean, and string values fail |
| `health_units` | Recent successful executions of all three named health probes |
| `call_counters` | Durable CDR and call-ledger observations before and after the same verification window |

Required checks cover service activity, loopback AMI/database bindings, private
ingress, verified mTLS, time synchronization, the delivery worker, callback
signature/replay/restart continuity, CDR read-back, backup, isolated restore,
and rollback. Parent calling evidence additionally requires disabled effect
flags, source/provenance/signature verification, and release-bound proof digests.

Zero counters cover active channels/calls, configuration drift, outbox depth
and age, retries, dead letters, quarantined/corrupt events, and event gaps.
If a metrics source reports fractional seconds, round a positive age **up**;
do not truncate it to zero. Do not clear or replay a queue to manufacture a pass.

For each key named in `HEALTH_UNITS`, supply `result: "success"`, integer
`exit_status: 0`, and an integer `last_success_age_seconds` between 0 and 300.
Compute that age from the actual successful probe execution, not collection
time or a timer's scheduled next run. Completed oneshot services are normally
inactive: `systemctl is-active` alone is insufficient. `reset-failed` does not
establish a successful execution.
The evaluator adds elapsed time since `captured_at` to that recorded age;
the successful execution must still be within 300 seconds at evaluation time.

`call_counters` requires `authority: "durable-cdr-and-call-ledger"`,
`same_observation_window: true`, and explicit integer zero for both
`calls_placed_before` and `calls_placed_after`. Use counts scoped to the
verification window from the durable authorities. Asterisk's process-lifetime
channel counter resets on restart and cannot establish this result.

The CLI uses the same evaluation as the HTTP route:

```sh
python -m control_plane_service.calling_readiness \
  --expected /protected/expected-calling-evidence.json \
  --observed /protected/observed-calling-evidence.json
```

Deploy the producer's additive `server_b` object and explicitly recorded
`safety.ENABLE_AGENT_PROVISIONING` and `safety.ENABLE_INTERNAL_TEST_CALLING`
fields with this gate. The publisher in `control_plane_service.calling_evidence`
uses the evaluator's flag list and refuses to invent missing observations;
see [the publishing contract](CALLING_READINESS_API.md#publishing-collector-observations).
Older
documents intentionally return `SERVER_B_EVIDENCE_MISSING`; no default silently
marks a legacy runtime ready. A `READBACK_MATCHES` result still sets
`production_activation_authorized: false` and `live_state_collected: false`.

## Runtime reconciliation order

1. Verify current host/release identity and preserve protected configuration,
   durable events, and backup evidence.
2. Publish and verify the exact reviewed canonical source artifact through the
   owning repository's release workflow. Do not copy feature-branch code into
   the active release or build a live-server replacement.
3. Reconcile Asterisk drift against the approved change records; never update
   the baseline just to silence its alert.
4. Investigate the legacy event gateway and the approved Middleware receiver.
   Preserve quarantined events and original identifiers. Delivery, replay, and
   migration require the bounded rollout's authorization and read-back.
5. Return from an expired/completed one-call test profile through the governed
   read-only deployment path. Do not reactivate dialing to make `/ready` green.
6. Re-run the health probes, mTLS and durable callback/CDR checks, isolated
   restore, and rollback rehearsal. Record unknown results as blockers.

Issue #259 remains open until its required runtime handoff and certification
are proven. Source CI and this evaluator alone do not satisfy that mission.
