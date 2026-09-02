# Server 65 provider read-only health evidence

Captured at `2026-09-02T17:30:00Z` from the Server 65 remediation environment. Only source-defined public health/readiness endpoints, DNS, and TLS metadata were queried. No authentication credential, provider command, message, email, SMS, call, or other external effect was used.

## Klyrow

Source authority explicitly defines `https://api.klyrow.com/healthz` and `/readyz`.

| Check | Result |
|---|---|
| Public DNS A | PASS — `37.27.128.39` |
| Authoritative DNS A | PASS — both authoritative nameservers returned `37.27.128.39` |
| HTTPS peer | PASS — `37.27.128.39` |
| TLS hostname verification | PASS — SAN contains `api.klyrow.com` |
| `GET /healthz` | PASS — HTTP 200 JSON |
| `GET /readyz` | PASS — HTTP 200 JSON |

## Telnexa

Source authority explicitly defines public `/healthz` and billing `/ready` endpoints.

| Check | Result |
|---|---|
| `sms.telnexa.co` public and authoritative DNS A | PASS — `37.27.128.39` |
| `api.telnexa.co` public and authoritative DNS A | PASS — `37.27.128.39` |
| HTTPS peer | PASS — `37.27.128.39` |
| TLS hostname verification | PASS — SAN contains both `sms.telnexa.co` and `api.telnexa.co` |
| `GET https://sms.telnexa.co/healthz` | PASS — HTTP 200 |
| `GET https://api.telnexa.co/healthz` | PASS — HTTP 200 JSON |
| `GET https://api.telnexa.co/ready` | PASS — HTTP 200 JSON |

## Integration gates not certified

Public health does not prove the private Server 65 integration contract. These remain FAIL until an approved bounded test proves them:

- mTLS client identity from `65.109.65.169`
- dedicated service-account audience and scopes
- tenant enforcement
- correlation and idempotency propagation
- timeout and retry policy
- durable reconciliation
- provider-side audit linkage
- fail-closed external-write capability state

```text
KLYROW_PUBLIC_HEALTH=PASS
TELNEXA_PUBLIC_HEALTH=PASS
KLYROW_INTEGRATION=FAIL
TELNEXA_INTEGRATION=FAIL
CALLS_PLACED=0
PRODUCTION_CHANGED=NO
```
