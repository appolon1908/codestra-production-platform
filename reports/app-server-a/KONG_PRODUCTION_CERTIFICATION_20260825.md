# Kong Production Certification — 2026-08-25

```text
KONG_CERTIFICATION=FAIL
CADDY_CERTIFICATION=PASS
UNEXPECTED_KONG_DRIFT=9
```

This is a fail-closed certification. No Caddy or live database-backed Kong
configuration was changed. Secrets, tokens, private keys, and certificate
contents are excluded from this report.

## Certification result

| Gate | Result | Evidence |
| --- | --- | --- |
| Runtime gateway | PASS | Kong Gateway 3.14.0.1 is running and healthy; database is reachable. |
| Database | PASS | `/status` reported `database.reachable=true`; `kong_datastore_reachable=1`. |
| Admin API privacy | PASS | Host bindings for ports 8000, 8001, and 8002 are loopback-only; no public Caddy route to Admin API was found. |
| Caddy → Kong connectivity | PASS | Public and direct protected-route status matrices matched. Caddy validation and public TLS verification passed. |
| Kong → middleware connectivity | FAIL | 18/19 service targets resolved and accepted TCP from Kong. `codestra-automation-gateway -> codestra-control-plane:8096` failed DNS and TCP. The global maintenance gate prevented application-level certification. |
| Authentication | FAIL | Missing and invalid credentials were rejected consistently, and a valid approved key passed authentication, but the global maintenance gate returned 503 before the request reached its intended upstream. No protected route was observed returning 2xx. |
| Rate limiting | PASS | 12 concurrent harmless authenticated requests produced ten 503 maintenance responses and two 429 responses. Caddy preserved 429; limit and remaining headers were present. Only one live Kong gateway participates, so the configured local policy is currently coherent. |
| Request ID / correlation | FAIL | Caddy and Kong logs contained the canary ID and every response had a unique `X-Kong-Request-Id`; middleware had no match because the maintenance gate stopped the request. Duplicate client `X-Correlation-ID` values are retained, so only `X-Kong-Request-Id` is a trusted unique audit identity. |
| Forwarded header integrity | PASS | Public spoof attempts for XFF, proto, host, and real IP were replaced. Kong observed the trusted edge address, canonical host, and HTTPS scheme. |
| Route protocol consistency | PASS | HTTPS-only routes matched through Caddy and through trusted loopback when `X-Forwarded-Proto: https` was supplied; missing/invalid auth returned 401. Public spoofed `X-Forwarded-Proto: http` was replaced with `https`. |
| Breero mTLS | BLOCKED | Kong has a configured CA and client certificate. The certificate is valid 2026-08-17 through 2026-11-15. A read-only direct mTLS request using the Kong-managed credential returned 200 with verified TLS and `{"status":"ok"}`. End-to-end Caddy → Kong → Breero remains intentionally blocked by the global maintenance gate. |
| Configuration drift | FAIL | The source-controlled canonical dry run reported nine unexpected `api.codestra.co` route names. Callback dry run additionally found `codestra-callback-control.protocols` live as HTTP while desired is HTTPS. `deck` is unavailable and `/opt/codestra/kong` is not Git-controlled. |
| Upstream health | FAIL | One live service target failed DNS/TCP, and the global maintenance gate prevents application health checks through Kong. |
| Monitoring | FAIL | Kong exposes useful metrics and alert rules exist under `/opt/codestra`, but no live Prometheus target or running Prometheus container was found. |
| Regression tests | PASS | 32 focused Kong/Caddy tests passed; hardened audit passed; Caddy validation, `/healthz`, and TLS verification passed. |

## Authentication and route scope

The four canonical API families have enabled route-scoped `key-auth`:

- `/v1/crm`
- `/v1/email`
- `/v1/sms`
- `/v1/webhooks`

JWT is enabled on the campaign automation, campaign result, callback, and
communication OAuth routes. Communication read/write routes also have
route-scoped key authentication. Breero health/API is intentionally public at
Kong but currently maintenance-gated. The mail API and token-certification
route do not have route-scoped authentication; their intended upstream or
service-level policy must be documented before certification.

Representative status evidence:

| Request | Public Caddy | Direct Kong | Invalid bearer |
| --- | ---: | ---: | ---: |
| GET `/v1/crm` | 401 | 401 | 401 |
| GET `/v1/email` | 401 | 401 | 401 |
| GET `/v1/sms` | 401 | 401 | 401 |
| POST `/v1/webhooks` | 503 | 503 | 503 |
| POST `/api/v1/control/messages` | 401 | 401 | 401 |
| GET `/api/v1/messages` | 401 | 401 | 401 |
| GET `/api/v1/callbacks` | 401 | 401 | 401 |

No token or authorization header appeared in response bodies or captured
certification output.

## Request identity policy

- Caddy replaces untrusted `X-Forwarded-For`, `X-Forwarded-Proto`,
  `X-Forwarded-Host`, and `X-Real-IP` values.
- Kong trusts the actual `codestra_edge` network (`172.19.0.0/16`) and
  loopback. The live Caddy-to-Kong address is inside that network.
- Client `X-Correlation-ID` is retained and echoed; it is useful context but is
  not unique or trusted because a client can reuse it.
- `X-Kong-Request-Id` is generated uniquely for every request and is the
  authoritative gateway audit identity.
- Final middleware policy remains uncertified until the middleware logs and
  persists `X-Kong-Request-Id` alongside the correlation ID.

## HTTPS-only route architecture

TLS terminates at Caddy. Caddy sends HTTP to Kong while setting the trusted
forwarded scheme to HTTPS. Kong has `trusted_ips=172.19.0.0/16,127.0.0.1/32`,
`real_ip_header=X-Forwarded-For`, and recursive real-IP processing enabled.
The HTTPS-only `/api/v1/control/messages` and `/api/v1/messages` routes matched
and enforced authentication through this architecture. No route protocol
change is justified.

## Breero mTLS

| Property | Observed |
| --- | --- |
| Kong service | `breero-production-api` |
| Upstream | `scraper.internal.codestra.agency:8443` |
| SNI | `scraper.internal.codestra.agency` |
| TLS verification | Enabled, depth 3 |
| Client certificate | Configured in Kong; CN `middleware-scraper-client` |
| Client expiry | 2026-11-15 02:54:50 UTC |
| Approved CA | Configured in Kong; expires 2036-08-14 |
| DNS/TCP | PASS/PASS from Kong network |
| Direct verified mTLS health | HTTP 200, `status=ok` |
| Public result | HTTP 503 `core_web_api_maintenance` before proxying |

The 503 is not evidence of missing mTLS. Kong logs show no upstream attempt for
these requests, and the managed global `request-termination` plugin generated
the response. Disabling that gate requires a separately approved production
activation decision.

## Upstream connectivity

| Kong Service | Upstream | DNS | TCP | TLS/mTLS | App Health | Result |
| --- | --- | --- | --- | --- | --- | --- |
| breero-production-api | scraper.internal.codestra.agency:8443 | PASS | PASS | PASS | PASS direct | BLOCKED through maintenance gate |
| codestra-automation-gateway | codestra-control-plane:8096 | FAIL | FAIL | N/A | NOT TESTED | FAIL |
| codestra-callback-api | codestra-middleware-integration-api-1:8095 | PASS | PASS | N/A | Blocked by gate/auth | PARTIAL |
| codestra-campaign-automation-api | codestra-middleware-integration-api-1:8095 | PASS | PASS | N/A | Blocked by gate/auth | PARTIAL |
| codestra-communication-control-plane | codestra-integration-control-plane-api-1:8096 | PASS | PASS | N/A | Blocked by gate/auth | PARTIAL |
| codestra-crm-api | codestra-kong-service-auth-adapter-1:8080 | PASS | PASS | N/A | Blocked by gate/auth | PARTIAL |
| codestra-email-api | codestra-email-reseller-api-1:8080 | PASS | PASS | N/A | Blocked by gate/auth | PARTIAL |
| codestra-mail-control-plane | codestra-mail-api:8098 | PASS | PASS | N/A | Blocked by gate | PARTIAL |
| codestra-sms-api | codestra-kong-service-auth-adapter-1:8080 | PASS | PASS | N/A | Blocked by gate/auth | PARTIAL |
| codestra-sms-dlr | codestra-sms-api-api-1:8080 | PASS | PASS | N/A | Blocked by gate/auth | PARTIAL |
| codestra-token-validator | identity-certification:8080 | PASS | PASS | N/A | Blocked by gate | PARTIAL |
| codestra-webhooks | codestra-middleware-event-gateway-1:8095 | PASS | PASS | N/A | 503 maintenance | PARTIAL |
| codestra-website-api | 10.40.0.3:8443 | PASS | PASS | Service declares HTTP | Blocked by gate | PARTIAL |
| codestra-website-forms | codestra-integration-control-plane-api-1:8096 | PASS | PASS | N/A | Blocked by gate/auth | PARTIAL |
| Five private standby/test services | Docker-private targets | PASS | PASS | N/A | Not production traffic | PASS connectivity |

## Runtime security

The live gateway is non-privileged, runs as `kong`, has a read-only root
filesystem, drops all capabilities, uses `no-new-privileges`, has a 2 GiB
memory limit, 2 CPU limit, PID limit 512, and `unless-stopped` restart policy.
Only loopback host bindings exist. Its internal Admin listener binds all
container interfaces but is not published publicly.

The exited `codestra-rbac-kong-app-20260822` container belongs to the isolated
RBAC rehearsal network and exited successfully. The exited
`codestra-kong-kong-migrations-1` container is the Compose one-shot migration
service and exited successfully. Neither participates in live traffic; both
are retained as rehearsal/migration provenance and were not deleted.

## Failure behavior

Services have finite connect/read/write timeouts and retries between zero and
five. The maintenance gate returns a controlled JSON 503 with correlation and
rate-limit headers. No disruptive failover test was performed. Existing Kong
metrics distinguish Kong-generated 401, 429, 500, and 503 responses. A live
Prometheus scrape is still required before observability can pass.

## Exact production blockers

1. `GLOBAL_KONG_MAINTENANCE_GATE_ENABLED`: global request termination returns
   `core_web_api_maintenance`, preventing valid end-to-end upstream evidence.
2. `KONG_UPSTREAM_DNS_FAILURE`: `codestra-automation-gateway` cannot resolve or
   connect to `codestra-control-plane:8096` from the live Kong container.
3. `UNEXPECTED_KONG_DRIFT=9`: canonical source/live dry run found nine
   additional public route names requiring explicit source ownership review.
4. `CALLBACK_PROTOCOL_DRIFT`: live callback control route is HTTP while the
   source-controlled reconciler requires HTTPS.
5. `KONG_MONITORING_NOT_LIVE`: metrics exist, but no live Prometheus Kong target
   was found.
6. `MIDDLEWARE_REQUEST_ID_EVIDENCE_MISSING`: the canary did not reach middleware,
   so cross-layer correlation cannot be certified.

## Warnings

- An invalid bearer request to the campaign policy route produced one Kong 500;
  the normal missing-token request produced 401. This requires plugin error-path
  investigation.
- The live source is split between this repository, the
  `/root/codestra-control-plane-gateway` repository, reconciler scripts, and a
  non-Git `/opt/codestra/kong` deployment directory. A single authoritative
  desired-state export is absent.
- The global correlation plugin retains duplicate client correlation IDs.
  Consumers must use `X-Kong-Request-Id` as the trusted unique identifier.
- The Breero client certificate expires 2026-11-15 and needs monitored renewal.

## Test evidence summary

- Hardened readiness audit: 3 Kong containers identified; one live healthy
  gateway, one RBAC rehearsal, one migration container; 19 services, 27 routes,
  and 115 plugins; Admin public bind none.
- Focused automated regression suite: 32 passed.
- Caddy validation: valid configuration.
- Public `/healthz`: HTTP 200; TLS verification result 0.
- Auth parity matrix: public/direct results matched on representative routes.
- Forwarded spoof test: all spoofable forwarding headers replaced.
- Rate limit test: 10 maintenance responses plus 2 HTTP 429 responses under
  twelve concurrent safe requests; headers present.
- Breero direct mTLS: HTTP 200, verified certificate, healthy JSON response.
- Canonical dry run: exited 2 with nine unexpected public route names.
- Campaign automation dry run: PASS.
- Callback dry run: failed on protocol readback mismatch.
- Monitoring: Kong metrics available; no live Prometheus Kong target.

```text
GIT_BRANCH=agent/control-plane-release-consolidation-20260822
BASELINE_COMMIT=a33beb6
CHANGES_APPLIED=certification report only; no live configuration changes
```
