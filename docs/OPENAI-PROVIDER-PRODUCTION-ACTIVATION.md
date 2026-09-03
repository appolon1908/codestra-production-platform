# OpenAI provider production activation

## Current authority

The immutable Middleware release already contains the governed OpenAI Responses
worker, but the canonical runtime graph did not define a container for it. This
package adds that missing runtime contract without activating the provider.

The exact bound release is:

- source SHA: `f199b6c40f4e467979e9a8b255a0e686321a182d`
- image: `ghcr.io/codestra-srl/codestra-middleware@sha256:ec2cf4ca73ff072fbdd48bda108a60f103526cb3e97a721abdf38435b010908b`
- required database head: `0056_klyrow_delivery_events`
- worker: `codestra-openai-01`
- service identity: `openai-responses-provider`
- maximum concurrency: `1`
- allowed project: `codestra-ai-console`

Merging this package has no production effect. The service is behind the
`openai-provider` Compose profile, uses `restart: "no"`, and all provider,
submission, orchestration, and worker-claim gates remain `false`.

## Secret handling

The API key must never be committed, pasted into a pull request, placed in a
Compose environment value, stored in a Docker image or label, emitted in logs or
evidence, copied to a browser, or installed on Server C.

Server A must receive these two independent protected files from the approved
secret-management path:

| Host file | Container file | Required metadata |
| --- | --- | --- |
| `/etc/codestra/secrets/openai-provider/api-key` | `/run/secrets/openai/api-key` | UID/GID `10001:10001`, mode `0400` |
| `/etc/codestra/secrets/openai-provider/safety-salt` | `/run/secrets/openai/safety-salt` | UID/GID `10001:10001`, mode `0400`, at least 32 random bytes |

The existing protected Middleware PostgreSQL URL is mounted read-only at
`/run/secrets/database_url`. Every bind mount disables automatic host-path
creation, so a missing file is a hard failure rather than an empty directory.

Verify only metadata and hashes of non-secret deployment files. Never print,
hash, upload, or retain the API key or safety-salt contents as evidence.

## Repository validation

Run from the protected release checkout:

```bash
python3 tools/validate_openai_provider_runtime_contract.py \
  --evidence-output /tmp/openai-provider-runtime-contract.json

python3 tests/test_openai_provider_runtime_contract.py

docker compose \
  --profile openai-provider \
  --file deploy/middleware/compose.openai-provider.yaml \
  config --quiet
```

Expected result:

```text
OPENAI_PROVIDER_RUNTIME_CONTRACT=PASS
```

This validates only the disabled runtime contract. It does not authenticate to
OpenAI, contact a server, migrate a database, register a worker, or authorize
production activation.

## Staging entry gate

Do not start the worker until all of the following are recorded against one
exact candidate:

1. The source SHA, image digest, and database migration head read back exactly.
2. The API-key and safety-salt files exist with the required ownership and mode,
   without exposing either value.
3. Egress is limited to verified TLS connections to `api.openai.com:443`; no
   redirect may receive the bearer credential.
4. The exact `codestra-openai-01` / `openai-responses-provider` registration is
   enabled with maximum concurrency one and the project allowlist is exactly
   `codestra-ai-console`.
5. A protected model-access probe passes for both source-locked model policies.
   Record only pass/fail, safe provider error class, request ID when safe, and
   latency. Do not retain prompt or response content.
6. Database, Odoo filestore, and configuration backups exist, including an
   off-host copy, and restore evidence is current.
7. Calls, emails, and SMS counters remain zero.

Render the complete production Compose graph before any start. The new service
must still show the immutable image, non-root user, read-only root filesystem,
no ports, no host-path creation, and every activation flag `false`.

## Controlled canary

Activation requires a separate, independently reviewed, root-controlled
override outside this repository. That override is not part of this package.
It may change only the bounded OpenAI and AI-orchestration gates needed for the
canary, preserve concurrency one, preserve the exact project allowlist, and
leave every telephony, email, SMS, Odoo-write, n8n-delivery, and broad external
delivery flag disabled.

Before the canary:

- prove that the previously certified Qwen worker remains available for
  rollback;
- prevent Qwen and OpenAI workers from claiming the same model profile at the
  same time;
- confirm queue depth and active leases;
- establish latency, error-rate, quota, and cost stop thresholds;
- attach independent approval to the exact deployment head.

The canary must cover authenticated chat, approved coding, streaming,
cancellation, timeout, tenant denial, project denial, usage limits, provider
authentication failure, rate limiting, transient failure, and exactly-once
result delivery. Prompts, responses, user identifiers, API keys, and
safety-identifier salts must not appear in evidence.

## Stop conditions

Stop and roll back immediately on any source or digest mismatch, database-head
drift, missing monitoring, credential exposure, unexpected redirect, model
denial, authentication failure, unsafe retry behavior, duplicate claim,
concurrency above one, cost or quota breach, latency/error regression, write
request, or movement in calls, emails, or SMS counters.

## Rollback

1. Disable new OpenAI claims and the OpenAI worker registration.
2. Wait for the active OpenAI lease count to reach zero, or use the governed
   expired-lease recovery path.
3. Stop the OpenAI worker.
4. Re-enable the previously certified Qwen registration and routing.
5. Verify queue depth, chat, coding, cancellation, exactly-once result
   delivery, and source/image readback.
6. Record RTO, RPO, data-integrity results, and sanitized health evidence.
7. Preserve Qwen credentials; this release does not revoke or remove them.

## Production certification state

The repository package remains
`BLOCKED_PENDING_PROTECTED_SECRETS_REGISTRATION_AND_STAGING_CANARY` until every
entry gate, canary check, rollback rehearsal, independent review, and immutable
readback is complete. A merge alone is not production certification.
