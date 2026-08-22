# SMS and email handshake certification — 2026-08-22

This is an evidence-bounded interim certification. No customer SMS or email was sent, no historical dead letter was replayed, and no secret value was recorded.

## Runtime inventory

| Component | Runtime | Address / listener | Health |
|---|---|---|---|
| Telnexa private adapter | remote private service | `telnexa.internal.codestra.agency` → `10.40.0.4:8443` | endpoint reachable; authenticated health not yet proven |
| Telnexa public API | remote public service | `https://sms.telnexa.co/send` | TLS/API parser reached; unauthenticated HTTP 400 |
| Klyrow-compatible email API | `codestra-beyvra-email-api-1` | `172.19.0.27:8080` | healthy |
| Canonical integration control plane | `codestra-integration-control-plane-api-1` | `172.18.0.35` / `172.19.0.14`, host `127.0.0.1:8096` | healthy and ready |
| Middleware | `codestra-middleware-1` | `172.18.0.26:8095` | healthy |
| Kong | `codestra-kong-kong-gateway-1` | `172.19.0.18`, host loopback `8000-8002` | healthy |
| n8n | `codestra-n8n-1` | `172.19.0.2:5678` | `/healthz` HTTP 200 |
| Odoo | `codestra-odoo-1` | `172.19.0.9:8069` | `/web/health` HTTP 200 |

The canonical `/api/v1/control/messages`, `/api/v1/messages/{id}`, `/api/v1/messages/{id}/events`, `/api/v1/control/messages/{id}/dispatch`, and `/api/v1/results/messages/{id}` contracts were deployed from protected commit `c6fe165`. Provider-specific APIs remain behind the canonical registry.

## Tests executed

- Communication control-plane focused suite: **15 passed**.
- SMS authentication, HMAC, replay, and completion suite: **14 passed**.
- Complete authoritative control-plane suite: **229 passed plus 9 subtests**; post-replay remediation focus: **36 passed**.
- Internal reachability: middleware→n8n, middleware→Odoo, middleware→SMS API, and middleware→email API returned HTTP 200 health/readiness responses.
- Public Telnexa send and private Telnexa endpoint both completed TLS and returned HTTP 400 without credentials. This proves reachability/parser access only, not authentication or delivery.
- Deployed canonical SMS and email requests reached `accepted` through simulator/test adapters with one registry record each; duplicate request returned the same UUID and modified-payload reuse returned HTTP 409.
- Signed Telnexa and Klyrow delivery events returned HTTP 202. Exact event-ID replay returned HTTP 409 after remediation; bad signatures and expired timestamps returned HTTP 401.
- Current Klyrow-compatible email API `dead_letter_count` metric is **0**. The historical 87-item statement is stale runtime documentation; no events were deleted or replayed.

## Certification decision

`FINAL_STATUS=FAIL`

The control plane and signed provider ingress are now substantially remediated. Final certification still cannot pass until Kong per-operation identities/scopes replace the current shared key-auth route, n8n execution IDs are captured for both provider events, and the Odoo communication timeline is proven end-to-end.

No PASS is inferred from container health alone.
