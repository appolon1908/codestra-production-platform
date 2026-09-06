# Odoo-to-VICIdial Production Calling Readiness

Assessment time: `2026-09-04T22:00Z`

Scope: Odoo -> middleware -> Kong/Caddy -> restricted VICIdial adapter.

Decision: **CONDITIONAL GO FOR A CONTROLLED PILOT; PRODUCTION DIALING REMAINS BLOCKED**

## Verified current state

| Gate | Result | Evidence |
|---|---|---|
| Repository regression suite | PASS | `111 passed, 9 subtests passed` |
| Odoo runtime | PASS | container healthy; public `/web/health` returned HTTP 200 |
| Middleware runtime | PASS | core, adapter-client, provisioning, policy, evidence, sync, n8n, and reconciliation containers healthy; core `/livez` and the adapter role's `/healthz` and `/readyz` probes returned HTTP 200 |
| Kong runtime | PASS | `kong health` passed; Admin status returned HTTP 200; Admin listeners bound to loopback |
| Caddy configuration | PASS | active `/etc/caddy/Caddyfile` validated; public TLS verification returned 0 |
| n8n runtime | PASS | public `/healthz` returned HTTP 200 |
| Server B private reachability | PASS | `10.40.0.2:8443` and compatibility port `9443` reachable |
| Public adapter isolation | PASS | public `65.21.67.207:8443` and `:9443` closed or filtered |
| Fail-closed feature state | PASS | middleware, adapter client, and provisioning runtime report `ENABLE_VICIDIAL_WRITES=false` and `SEND_EVENTS=false` |
| Controlled destination authorization | BLOCKED | no completed, signed one-call authorization package |
| Business/compliance policy | BLOCKED | exact campaign, calling hours, consent, DNC, recording, and destination approval not supplied |
| End-to-end pilot call reconciliation | NOT_TESTED | no authorized call ID, VICIdial ID, Odoo record ID, or correlation ID exists |

## Health-probe discrepancy resolution

The initial diagnostic requests to `http://127.0.0.1:8095/health` and
`http://127.0.0.1:8095/ready` were executed inside the middleware
VICIdial-adapter role container. That role exposes only the canonical
`/healthz` and `/readyz` routes, so the non-suffixed paths correctly returned
HTTP 404. They were incorrect diagnostic paths, not failed health or readiness
checks. The core middleware role supports both aliases, which explains why the
WebSocket gateway had remained ready despite using the older `/health` alias.

The container's configured health check identifies the canonical endpoints as
`/healthz` and `/readyz`. Direct in-container verification returned:

```text
200 http://127.0.0.1:8095/healthz
200 http://127.0.0.1:8095/readyz
container health=healthy
failing_streak=0
```

The platform-standard liveness probe was also verified against the core
middleware HTTP service:

```text
200 http://127.0.0.1:8095/livez
{"status":"alive","service":"middleware-integration-api"}
```

Resolution: **PASS — false alarm caused by diagnostic path mismatch.**

The source and deployed WebSocket-gateway configuration were subsequently
standardized on `http://middleware:8095/healthz`. The reproducible production
override is versioned in
`deploy/architecture-remediation/compose.websocket-gateway.yaml`. The gateway
was recreated with the same immutable image digest and verified as follows:

```text
container health=healthy
failing_streak=0
GET /readyz = 200
internal_event_source=true
```

## Activation boundary

Do not change `ENABLE_VICIDIAL_WRITES`, `SEND_EVENTS`, or any production dialing
flag until `VICIDIAL_ONE_CALL_PRODUCTION_AUTHORIZATION_PACKAGE.md` contains an
exact campaign, list, agent, extension, trunk, controlled destination, validity
window, compliance evidence, owners, rollback reference, and signatures.

The first activation must remain one manual call to a controlled destination.
Predictive dialing, customer lists, callbacks, transfers, recording-content
access, SMS, email, and unrelated campaign activation remain disabled.

## Pilot completion criteria

1. Capture a fresh pre-change backup and prove the rollback reference.
2. Validate the signed pilot authorization and maintenance window.
3. Enable only the minimum call-path flags for the exact pilot scope.
4. Place one manual call to the approved controlled destination.
5. Reconcile Asterisk/VICIdial identifiers, middleware correlation and event
   identifiers, and the normalized Odoo call record.
6. Confirm no duplicate lead, call record, callback, transfer, message, or
   recording-content side effect.
7. Restore the fail-closed flag state immediately after the pilot unless a
   separately signed persistent-production authorization exists.
8. Preserve sanitized evidence and record the final GO/NO-GO decision.
