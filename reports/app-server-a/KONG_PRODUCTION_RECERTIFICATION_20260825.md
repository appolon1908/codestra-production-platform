# Kong Production Recertification — 2026-08-25

```text
KONG_CERTIFICATION=FAIL
CADDY_CERTIFICATION=PASS
```

This recertification remained fail-closed. Caddy was not changed. The global
maintenance gate was not weakened or removed because the approved production
operator reports that the runtime activation safety conditions are not met.
No secret, token, private key, certificate content, or database URL is included.

## Result

| Gate | Result | Evidence |
| --- | --- | --- |
| Runtime gateway | PASS | Kong Gateway 3.14.0.1 is healthy. |
| Database | PASS | Kong reports the datastore reachable; Prometheus reports `kong_datastore_reachable=1`. |
| Admin API privacy | PASS | Admin API listens only on host loopback (`127.0.0.1:8001`). |
| Caddy to Kong | PASS | Direct/public parity holds for the representative API routes; public TLS and Caddy validation pass. |
| Kong to middleware | FAIL | The automation target now resolves and accepts TCP, but the global maintenance plugin prevents the required application canary. |
| Authentication | FAIL | Missing and invalid credentials remain rejected, but a valid credential cannot be certified as reaching an upstream while maintenance is active. |
| Rate limiting | PASS | Previous safe test produced 10 controlled 503 responses and 2 preserved 429 responses with rate-limit headers. |
| Request ID / correlation | FAIL | `X-Kong-Request-Id` is the trusted gateway identity, but propagation into middleware cannot be observed before the gate is safely opened. |
| Forwarded header integrity | PASS | Caddy replaces public spoof values and Kong trusts only the actual edge/loopback networks. |
| Route protocol consistency | PASS | Both callback routes now use HTTPS semantics and pass source/live reconciliation behind trusted TLS forwarding. |
| Breero mTLS | PASS | Direct verified mTLS health returned HTTP 200; the configured client certificate expires 2026-11-15. |
| Configuration drift | PASS | Canonical dry run reports `UNNECESSARY_PUBLIC_ROUTES=0`; all nine formerly unexpected routes have explicit production ownership. |
| Automation gateway DNS | PASS | Kong resolves `codestra-integration-control-plane-api-1` to the production control-plane container and accepts TCP on 8096. |
| Upstream health | FAIL | DNS/TCP blocker is repaired and Breero health passes, but application health through Kong remains blocked by maintenance. |
| Monitoring | PASS | Existing `codestra-monitoring` Prometheus is healthy, the Kong target is UP, datastore metric is 1, and five Kong alert rules are loaded and healthy. |
| Maintenance gate | ACTIVE | Global request termination remains enabled and returns controlled HTTP 503. |
| Canary | BLOCKED | The approved operator safety state does not permit production traffic activation. |
| Regression tests | PASS | 46 focused tests pass, above the previous 40-test baseline; shell/static and live checks pass. |

## Remediation evidence

### Automation gateway

- Authoritative target: `codestra-integration-control-plane-api-1:8096`.
- Runtime service: `api` in Compose project
  `codestra-integration-control-plane`, on `codestra_backend` and
  `codestra_edge`.
- Source and live Kong service were reconciled to the authoritative production
  container; the failed candidate stack was not used.
- From the live gateway: DNS resolves to `172.19.0.29` and a TCP open succeeds.

```text
AUTOMATION_GATEWAY_DNS=PASS
AUTOMATION_GATEWAY_TCP=PASS
AUTOMATION_GATEWAY_TARGET=codestra-integration-control-plane-api-1:8096
```

### Configuration drift and callback protocol

The nine routes are all classified `REQUIRED_PRODUCTION` in the canonical
manifest with their owning service, repository domain, source declaration, and
security policy:

- `cod-web-out-email-production`
- `codestra-callback-control`
- `codestra-callback-read`
- `codestra-campaign-policy-check`
- `codestra-campaign-result-submit`
- `codestra-communication-canonical-read`
- `codestra-communication-canonical-write`
- `codestra-communication-oauth-shadow-create`
- `codestra-mail-api`

Canonical reconciliation now reports zero unexpected public routes. The live
callback routes use `protocols=https`, host `api.codestra.co`, and the supported
JWT plus scope-enforcement pre-function policy (`callbacks.write` and
`callbacks.read`). Rate limiting, request sizing, and correlation remain
enabled. An attempted stale Enterprise-only OIDC declaration was rejected by
Kong and was not used to weaken the working JWT policy.

```text
UNEXPECTED_KONG_DRIFT=0
CALLBACK_PROTOCOL_DRIFT=0
```

### Monitoring

The existing `/opt/codestra/operations/monitoring/compose.monitoring.yaml`
stack was restored; no duplicate stack was created. Prometheus is healthy with
restart policy `unless-stopped`. Its Kong scrape is UP at the private Admin
metrics endpoint. The loaded healthy alert rules cover gateway availability,
datastore availability, server error rate, P95 latency, and metric errors.

```text
KONG_PROMETHEUS_TARGET=UP
KONG_METRICS_SCRAPE=PASS
KONG_MONITORING=PASS
```

### Maintenance authority and canary

The active global plugin is `request-termination`, instance
`codestra-core-web-api-traffic-gate`, returning HTTP 503 with
`core_web_api_maintenance`. The approved operator status evidence is
`/var/lib/codestra-production-operator/evidence/20260825T232709Z-1180062-status.json`.
Although the owner window waiver is valid, activation safety is not satisfied:
active calls/channels are not proven zero, the telephony probe fails, and SIP
registrations are present. The operator is intentionally not a safety bypass.

```text
MAINTENANCE_GATE_CHANGE_APPROVED=NO
CADDY_KONG_MIDDLEWARE_CANARY=BLOCKED
```

## Regression evidence

- Focused automated suite: `46 passed in 0.77s`.
- Canonical Kong dry run: `UNNECESSARY_PUBLIC_ROUTES=0`.
- Callback dry run: `KONG_CALLBACK_ROUTES=PASS`.
- Direct/public status parity:
  `/v1/crm` 401/401, `/v1/email` 401/401, `/v1/sms` 401/401,
  `/v1/webhooks` 503/503, `/api/v1/control/messages` 401/401, and
  `/api/v1/callbacks` 401/401.
- Public `/healthz`: HTTP 200 with verified TLS.
- Caddy configuration validation: PASS; Caddy configuration unchanged.
- Kong Admin remains loopback-only; maintenance remains global and enabled.
- `bash -n` and `git diff --check`: PASS.

## Remaining production blockers

1. `MAINTENANCE_ACTIVATION_SAFETY_NOT_MET`: the approved operator does not
   authorize activation while telephony runtime safety checks fail.
2. `NO_APPROVED_NARROW_CANARY_BYPASS`: the current gate is global; no reviewed
   mechanism exists to pass one request without activating production traffic.
3. `VALID_AUTH_UPSTREAM_EVIDENCE_BLOCKED`: a valid credential cannot reach the
   intended middleware while the global gate remains active.
4. `MIDDLEWARE_X_KONG_REQUEST_ID_EVIDENCE_BLOCKED`: middleware propagation and
   logging of `X-Kong-Request-Id` cannot be certified before a safe canary.
5. `APPLICATION_UPSTREAM_HEALTH_BLOCKED`: full health through Kong cannot be
   observed while maintenance terminates requests before proxying.

## Warnings

- Renew and deploy the Breero client certificate before 2026-11-15.
- Client-provided `X-Correlation-ID` remains contextual only; it must not be
  treated as a trusted unique audit identity.
- The two exited Kong-related containers are retained as RBAC rehearsal and
  migration provenance; neither participates in live traffic.

