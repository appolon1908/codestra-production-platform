# 07 — Codestra Middleware Application Review (Step 11)

Scope: `codestra-app` host only (per audit scope decision — VICIdial/provider/scraper hosts excluded from this report). Read-only. All secret values redacted.

## Source of truth

- GitHub repo: **`Codestra-SRL/codestra-middleware`** (private, default branch `main`), NOT any `appolon1908-hue/*` repo. This is a different GitHub org than the one the audit's `gh` session is authenticated as by default context, but API access was confirmed working (`gh api repos/Codestra-SRL/codestra-middleware` succeeded).
- 15+ live containers on this host run this one repo's image at **three different commits simultaneously** (see finding M-1).
- Local checkout at `/opt/codestra/middleware` is **not usable as ground truth**: it is checked out on branch `postiz-social-orchestration-20260804` at commit `7b9451b` (2026-08-04), ~3 weeks behind `origin/main` (`d178cdea`, 2026-08-22, PR #262 merged), and is dirty (4 modified files, 8+ untracked files/dirs including a whole untracked module `app/core/vicidial_dispositions.py` and its test). All code evidence below was taken from `git show <verified-deployed-sha>:path` or `origin/main`, not this working tree.

## Runtime topology as actually observed

The compose project `codestra` (config files under `/opt/codestra/compose/`, 7+ overlay YAML files merged, plus **two ad-hoc host-level overrides** loaded from `/home/codestra-admin/releases/*.override.yaml` outside the tracked compose directory — `callback-production-20260822.override.yaml` and `campaign-crm-middleware-d30babd.override.yaml`) runs ~21 distinct middleware roles from this one repo: `middleware`, `middleware-integration-api`, `middleware-odoo-result-worker`, `middleware-notification-worker`, `middleware-scheduler`, `middleware-evidence-runner`, `middleware-policy-engine`, `middleware-sync-worker`, `middleware-n8n-runtime-worker`, `middleware-social-n8n-delivery-worker`, `middleware-telephony-provisioning`, `middleware-vicidial-adapter`, `middleware-pjsip-adapter`, `middleware-reconciliation-worker`, `middleware-extension-allocator`, `middleware-event-gateway`, `middleware-external-webhook-worker`, `middleware-breero-odoo-worker`, `middleware-postly-polling-worker`, `middleware-webphone-session-issuer`. A parallel, fully separate `-staging` stack of most of these also runs concurrently on the same host.

Every container's actual entrypoint is wrapped by `/opt/codestra/safety/live-delivery-admission.sh` (bind-mounted read-only into every container), which is a hard, fail-closed kill switch:

```sh
for flag in LIVE_SMS_DELIVERY LIVE_EMAIL_DELIVERY LIVE_PSTN_DIALING; do
    eval "value=\${$flag-}"
    if [ "$value" != "false" ]; then
        echo "live-delivery admission denied: $flag must be exactly false" >&2
        exit 78
    fi
done
exec "$@"
```
**Every one of the ~21 production middleware containers currently refuses to even start unless all three live-delivery flags are exactly `false`.** This was confirmed indirectly: `/readyz` on several services (`webphone-session-issuer`, `event-gateway`, `policy-engine`, `telephony-provisioning`, `extension-allocator`) reports `"delivery":"disabled"`. **This is the single most important fact for the platform's overall production-readiness verdict**: as currently configured, the middleware fleet cannot place a real PSTN call, send a real SMS, or send a real email even if every upstream system (VICIdial, Kong, Odoo) is otherwise perfect. This is almost certainly intentional given the audit's read-only mandate, but it means "PRODUCTION_READY" cannot be assessed as YES purely from this host's current runtime state — flip state must be verified separately with the platform owner. (Cross-reference: `00_EXECUTIVE_SUMMARY.md`, `20_PRODUCTION_BLOCKERS.md`.)

## Findings

**M-1 — P2 — Fleet running 3+ divergent commits of the same service with no visible rollout coordination**
- Evidence: `docker inspect` labels — `codestra-middleware-1` (compose service `middleware`) → `io.codestra.build.revision=b3ca9aa4` (2026-08-11); `codestra-middleware-vicidial-adapter-1` → same `b3ca9aa4`; `codestra-middleware-integration-api-1` → `35448ef8` (2026-08-23, different base image entirely: `cgr.dev/chainguard/python` vs `docker.io/library/python`); `codestra-middleware-webphone-session-issuer-1` → `80954a1e` (2026-08-19). All three SHAs verified to exist in `Codestra-SRL/codestra-middleware` history via `gh api` (not fabricated/orphaned — good).
- Expected: a documented release/pinning mechanism showing which SHA is "current production" and why other services lag.
- Risk: config/behavior drift between services that talk to each other (e.g., a schema or contract change landed in `35448ef8` may not exist yet in the `b3ca9aa4` build other services expect).
- Recommended fix: adopt one pinned `RELEASE_ID`/`SOURCE_SHA` per deploy across the whole compose project; the `/version` endpoint (added in `35448ef8`, see M-2) is the right mechanism once populated.
- GitHub repo: `Codestra-SRL/codestra-middleware`. Suggested branch: `audit/pin-middleware-fleet-version`.

**M-2 — P3 — `/version` endpoint deployed but non-functional (env vars unset)**
- Evidence: `codestra-middleware-integration-api-1` → `GET /version` returns `{"service":"middleware-integration-api","source_sha":"unknown","release_id":"unknown","image_digest":"unknown"}`. The endpoint (`app/entrypoints/runtime.py`, added in commit `35448ef8`, "Expose immutable version endpoint on API runtimes") reads `SOURCE_SHA`/`RELEASE_ID`/`IMAGE_DIGEST` from the environment, but none of the compose files set them for this service.
- Risk: low by itself, but it defeats the one purpose-built mechanism for runtime-to-source GitHub reconciliation (Step 2), forcing reliance on `docker inspect` labels instead.
- Fix: set `SOURCE_SHA`/`RELEASE_ID`/`IMAGE_DIGEST` build args in the image build pipeline and pass through as env in compose.
- File: `/opt/codestra/compose/*.yaml` (env block for `middleware-integration-api` and all other services using the `runtime.py` factory). Test required: `curl /version` returns real values post-fix.

**M-3 — P3 — Compose service name `middleware` runs the `integration_api` entrypoint, not a distinct "middleware" role**
- Evidence: `docker inspect codestra-middleware-1 --format '{{.Config.Cmd}}'` → `python -m app.entrypoints.integration_api` — identical entrypoint module to the separately-named `codestra-middleware-integration-api-1` container. Confirmed live: `codestra-middleware-1`'s own `/healthz` payload self-reports `"service":"middleware-integration-api"` even though its compose service/container name is `middleware`.
- Risk: none functionally, but it is a real operator/monitoring hazard — anyone alerting or debugging by container name `codestra-middleware-1` is actually looking at a second, differently-configured instance of the integration API (different DB secret path: `middleware-runtime/...` vs `middleware-runtime/middleware-integration-api-database-url`), not a distinct "core middleware" service. Likely an old/legacy naming holdover from before the integration-api was split out.
- Recommended fix: rename the `middleware` compose service to reflect its actual role, or confirm/document that it is an intentional second integration-api replica and rename accordingly (e.g. `middleware-integration-api-legacy`).

**M-4 — P4/informational — Staging-only debug endpoints (`/v1/n8n/test/fault/{code}`, `/v1/n8n/test/delay/{ms}`) are wired into the same FastAPI app used in production, gated only by `require_staging()` checking `settings.environment`**
- Evidence: `app/api/v1/n8n_staging.py:106-119`; router mounted unconditionally in `app/main.py:33` and `app/entrypoints/integration_api.py:28`. **Verified safe at runtime**: `require_staging()` raises `HTTPException(404)` unless `settings.environment` is `staging`/`test`/`integration`; empirically the production `middleware-integration-api-1` container's routes under `/v1/n8n/...` are not the ones probed here but the code path is confirmed environment-gated, not auth-gated. No live fault/delay injection was observed or attempted (Phase 1 read-only).
- Residual risk (P3, not P0/P1): correctness of this gate depends entirely on `ENVIRONMENT` being set correctly per-service in compose; a single misconfigured env var would silently re-expose chaos-injection endpoints in production. Recommend moving fault/delay test routes to a separate router only imported in non-production entrypoint modules, rather than relying on a runtime string check, as defense in depth.

**M-5 — P3 — Three workers report Prometheus-mounted or connection-refused instead of the expected `/readyz` JSON**
- Evidence: `codestra-middleware-n8n-runtime-worker-1` and `codestra-middleware-external-webhook-worker-1` → `Connection refused` on `127.0.0.1:8095/readyz` despite `docker ps` showing "healthy". `codestra-middleware-scraper-odoo-delivery-worker-1` → `/readyz` returns raw Prometheus metrics text instead of the expected JSON body.
- Note: Docker reports these containers "healthy," so the actual `HEALTHCHECK` command (which may hit a different internal path/process check) is presumably passing — this is specifically about the `/readyz` HTTP contract being inconsistent across the fleet, not about actual downtime. Marked **UNVERIFIED** as a functional problem; confirmed only as an inconsistency in the health/metrics contract across services that should share one.
- Recommended fix: standardize one health/ready/metrics contract (path + response shape) across every service built from this entrypoint factory.

**M-6 (positive / verified) — Real production foundations exist and are not placeholders**
Contrary to what the audit's own framing invites you to assume, a source-level check found: **zero** `TODO`/`FIXME`/`NotImplementedError` occurrences and **zero** bare-`pass` stub function bodies anywhere in `app/` (76 files). Concretely present and wired in: an `IdempotencyRecord` DB table with a unique `(scope, key_hash)` constraint plus a dedicated `/api/v1/automation/idempotency/check` endpoint; an outbox pattern (`app/workers/outbox.py`, `app/core/reliability.py`, `app/workers/reconciliation.py`); a dead-letter worker (`app/workers/dead_letter.py`) with a documented replay endpoint (`POST /api/v1/operations/dead-letters/{item_id}/replay`); HMAC webhook signature verification with a TTL/replay window (`app/core/security.py: verify_ingestion_signature`, used on `/api/v1/events/vicidial` and `/api/v1/automation/events`); a real `CircuitBreaker` class (`app/core/delivery.py`) and per-adapter `httpx` timeouts (e.g. `app/adapters/vicidial/mtls_client.py`); a global bearer-auth ASGI middleware (`app/main.py: control_request_guard`) enforcing auth on every `/api/` and `/v1/` path except an explicit 3-path allowlist that uses payload-signature auth instead; and at least one real 429 rate-limit enforcement point (`app/api/v1/mappings.py: _rate_limit`).
- **Not fully verified** (needs deeper review than this pass allows, marked UNVERIFIED rather than PASS): whether `business_unit`/tenant scoping columns present on 5 tables in `app/db/models.py` are consistently enforced on *every* read/write query path, or only on some. This is the kind of thing that looks fine per-table and fails at one overlooked query — recommend a dedicated follow-up pass specifically grepping every query against tenant-scoped tables for a `.filter(business_unit=...)`/equivalent.

## Not assessed in this pass (flag for follow-up, not silently dropped)
- The other ~14 `/opt/codestra/middleware-*` directories on disk (`middleware-fixture-6198-*` ×6, `middleware-rc4-vex-governance`, `middleware-lifecycle-contract-v1`, etc.) were not opened — they read as abandoned/completed remediation working copies from prior agent runs, not sources of anything currently deployed (nothing in `docker inspect` image labels pointed at them), but this was not exhaustively confirmed for all ~24 directories under `/opt/codestra` matching `middleware*`.
- Deep line-by-line review of all 76 `app/` files was not performed; review was targeted at routing, auth, idempotency, outbox, webhook verification, rate limiting, and circuit breaking, per Step 11's explicit checklist.
- Kong/Caddy-level exposure of the endpoints inventoried here (i.e., whether `/v1/n8n/...` or any internal-only path is reachable from the public internet) is out of scope for this report — see `08_KONG.md` / `09_CADDY.md`.
