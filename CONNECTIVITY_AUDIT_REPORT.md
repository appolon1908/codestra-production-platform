# Middleware API Connectivity Audit Report

Audit date: 2026-08-15 UTC

Branch: `agent/middleware-n8n-control-plane`

Mode: production-safe; Telnexa simulator, Klyrow test, Kyqra test URLs only

## Executive result

The locally executable control-plane contract is healthy: 189 tests pass and three real-NATS tests skip because no audit NATS URL is supplied. HMAC positive/negative/stale tests, replay and idempotency conflict handling, retries/DLQ replay, circuit opening, correlation lookup, Telnexa simulation, Klyrow test delivery, Kyqra safe-job submission, consent, suppression, and tenant isolation all have executable evidence.

The requested production end-to-end audit is **BLOCKED by host identity and access**, not represented as a false PASS. The session runs on `49.12.145.107` / VLAN 4001 `10.40.0.3`, while the mission identifies `65.109.65.169` / `10.40.0.1`. The real middleware answers `GET http://10.40.0.1:8095/health` with HTTP 200 and `{"status":"ok","mode":"middleware"}`, but the available `codestra-middleware-operator` key is rejected. No Odoo or n8n runtime exists on the current host. Consequently provider credentials, live workflows, queues, certificates, logs, and positive production authentication cannot be inspected or exercised.

No real SMS, email, crawler target, Odoo write, direct Odoo PostgreSQL write, workflow mutation, or destructive action occurred.

## Required matrix

`Functional PASS` below means an executable local safe adapter/contract test passed. `Overall BLOCKED` means production positive-authentication and destination evidence remains inaccessible.

| Integration | Direction | Network | Auth | Functional | Idempotency | Retry/DLQ | Overall |
|---|---|---|---|---|---|---|---|
| Odoo | Middleware -> Odoo | FAIL | FAIL | FAIL | PASS | PASS | BLOCKED |
| Odoo | Odoo -> Middleware | PASS | FAIL | PASS | PASS | PASS | BLOCKED |
| n8n | Middleware -> n8n | FAIL | FAIL | FAIL | PASS | PASS | BLOCKED |
| n8n | n8n -> Middleware | PASS | FAIL | PASS | PASS | PASS | BLOCKED |
| Telnexa | Middleware -> Telnexa | PASS | PASS | PASS | PASS | PASS | BLOCKED |
| Telnexa | Telnexa -> Middleware | PASS | FAIL | PASS | PASS | PASS | BLOCKED |
| Klyrow | Middleware -> Klyrow | PASS | PASS | PASS | PASS | PASS | BLOCKED |
| Klyrow | Klyrow -> Middleware | PASS | FAIL | PASS | PASS | PASS | BLOCKED |
| Kyqra | Middleware -> Kyqra | PASS | PASS | PASS | PASS | N/A | BLOCKED |
| Kyqra | Kyqra -> Middleware | PASS | FAIL | PASS | PASS | PASS | BLOCKED |

Evidence interpretation:

- Odoo/n8n ingress network PASS: the live middleware health listener is reachable; authenticated ingress paths exist and local signed HTTP contract tests pass. Positive live credentials are unavailable, hence Auth FAIL and Overall BLOCKED.
- Odoo/n8n egress FAIL: no live destination or runtime credential can be seen from this host. The local worker contract preserves correlation and has bounded retries/DLQ.
- Telnexa/Klyrow/Kyqra outbound PASS: safe adapters returned `sim-*`, `test-*`, and `test-job-*`; no external delivery occurred. This does not claim production provider connectivity.
- Provider ingress Auth FAIL: missing/invalid credentials are rejected in tests, but no valid production credential was accessible for a positive live test.

## Security, resilience, and operations

| Control | Result | Live evidence |
|---|---|---|
| SSH/service identity | BLOCKED | key fingerprint `SHA256:+IBJr4dwVz2NTJOD9nNJUvuOV/gJZpS6d/OoUyecYE4`; rejected for root/codestra/middleware/operator at `10.40.0.1` |
| Private vSwitch | FAIL | expected `.1` on this host; observed VLAN 4001, MTU 1400, `10.40.0.3`; `.1` ICMP succeeds; `.2` does not answer |
| Private database/queue exposure | PASS on current host | no host listeners on 5432, 6379, 5672; Docker databases/Redis/NATS have no public published ports |
| Middleware ingress | PASS reachability | `10.40.0.1:8095/health` HTTP 200 |
| TLS | BLOCKED | TLS at `.1:443/8443` could not complete; cert/SAN/chain/renewal cannot be inspected without middleware access |
| mTLS | BLOCKED | repository declares client-certificate paths for NATS/VICIdial, but no live certificate evidence is accessible |
| API keys | PASS locally / BLOCKED live | plaintext or SHA-256 service-key validation tested; positive production identity unavailable |
| HMAC | PASS locally / BLOCKED live | SHA-256 canonical signature accepted; invalid/stale signatures rejected |
| Replay protection | PASS | identical event returns duplicate; changed payload under same identity returns 409 conflict |
| Idempotency | PASS | events, messages, and crawler jobs deduplicate; conflicting duplicates are rejected |
| Retry/DLQ | PASS locally | exponential `2^attempt` delay capped at 300s, bounded attempts, dead-letter, authenticated replay and audit |
| Circuit breaker | PASS locally | opens at configured failure threshold; cooldown/half-open allowance and successful close are implemented |
| Correlation ID | PASS locally | persisted in ledger, queryable tenant-scoped, forwarded as `X-Correlation-Id` to providers/Odoo/n8n |
| Health/readiness | PARTIAL | live `/health` PASS; `/ready`, dependency degradation and provider health BLOCKED by access |
| Monitoring | PARTIAL | current host runs healthy Prometheus/Grafana/Loki/Alertmanager/blackbox; middleware scrape/runtime evidence inaccessible |
| Odoo DB integrity | PASS source / BLOCKED runtime | no control-plane Odoo PostgreSQL connection; Odoo delivery uses HTTP URL; live process/env unavailable |

## Repairs completed

- Added `POST /v1/crawler/jobs` and tenant-scoped `GET /v1/crawler/jobs/{id}`.
- Restricted safe crawler targets to localhost or reserved `example.*` test hosts.
- Added Kyqra fail-closed production authorization and private URL enforcement.
- Added crawler-job idempotency, correlation persistence, OpenAPI contract, environment wiring, and tests.
- Added the repeatable safe audit command and machine-readable evidence artifact.

## Conclusive blockers and owner action

1. Infrastructure owner must run this audit on `65.109.65.169` or restore the operator public key on `10.40.0.1` for a documented least-privilege account. The exact available fingerprint is above.
2. Middleware operator must provide secret-file references (not secret values) for the five service identities and permit positive safe webhook tests.
3. Odoo/n8n owners must expose their approved safe test records/workflows to the middleware identity. No such runtime is present here.
4. TLS owner must provide access to the private SNI/CA/client certificate path so hostname, chain, expiry, renewal and mTLS can be proven.
5. Queue owner must supply an isolated `NATS_URL` and audit credentials to execute the three skipped real-JetStream tests without touching production messages.

No other locally executable audit or repair remains.
