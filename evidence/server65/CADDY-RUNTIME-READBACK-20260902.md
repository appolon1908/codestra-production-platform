# Server 65 Caddy runtime read-back

Captured read-only at `2026-09-02T17:24:33Z` using the approved `codestra-admin` operator and the exact-command `/usr/local/sbin/codestra-caddyctl` interface. No SSH configuration, sudo policy, service, configuration, backup, or runtime state was changed.

## Approved operator surface

The installed sudo policy permits fixed `codestra-caddyctl` actions. This validation invoked only:

- `status`
- `validate`
- `health`
- `config-test`
- `version`

Mutation-capable actions were not invoked. The source-only validator proposed by Caddy PR #42 was not installed.

## Results

| Gate | Result | Evidence |
|---|---|---|
| SERVICE_ACTIVE | PASS | `caddy.service` was active and running from `/etc/caddy/Caddyfile`. |
| CONFIG_VALIDATE | PASS | `caddy validate` returned `Valid configuration`. |
| CONFIG_TEST | PASS | The operator configuration test returned `Valid configuration`. |
| MTLS_SNI_ENFORCEMENT | PASS | Adaptation enabled strict SNI/Host enforcement for both servers because TLS client authentication is configured. |
| PUBLIC_DNS | PASS | `api.breero.com` resolved to `65.109.65.169`. |
| TLS | PASS | HTTPS connected to `65.109.65.169:443`; the certificate CN is `api.breero.com` and is valid from 2026-08-20 through 2026-11-18. |
| SECURITY_HEADERS | PASS | Response included HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, restrictive permissions policy, and strict-origin referrer policy. |
| EDGE_HEALTH | FAIL | Approved `codestra-caddyctl health` failed because `api.breero.com` returned HTTP 503. Direct `/health` read-back also returned 503. |
| READINESS_ROUTE | FAIL | `/readiness` and `/ready` returned 404. |
| VERSION_ROUTE | FAIL | `/version` returned 404. The local operator reported Caddy build `e2eee6a7fce366321294c9c2a79f3146891dcbdf+modified`; this is recorded without inferring source drift. |
| EDGE_SECRET_REDACTION | FAIL | The installed interface does not produce structural proof that every access log redacts Authorization, API-key headers, and API-key query parameters. No credential-bearing request was sent. |
| CANONICAL_SOURCE_ALIGNMENT | FAIL | Caddy PR #42 is not merged or installed, and no exact live configuration checksum was returned by the installed operator interface. |

## Public route diagnostics

The root path returned HTTP 404, proving TLS termination but not application health. The `/health` response contained only a generic message field when inspected structurally; no response body or potentially sensitive value is retained here.

## Verdict

```text
CADDY=FAIL
EDGE_SECRET_REDACTION=FAIL
PRODUCTION_CHANGED=NO
SSH_CHANGED=NO
```

Required remediation is to restore the `api.breero.com` health dependency, define canonical readiness/version behavior, merge and install the reviewed read-only validator through approved infrastructure change control, then rerun configuration checksum and per-log redaction validation.
