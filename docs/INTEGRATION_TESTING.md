# Integration Testing

Configure protected, audit-identity-owned files for the production Telnexa mTLS
client certificate, private key, server trust CA, and bearer token, then run:

```bash
export PRIVATE_GATEWAY_AUDIT_CLIENT_CERT_FILE=/protected/path/client-fullchain.crt
export PRIVATE_GATEWAY_AUDIT_CLIENT_KEY_FILE=/protected/path/client.key
export PRIVATE_GATEWAY_AUDIT_CA_FILE=/protected/path/root-ca.crt
export PRIVATE_GATEWAY_AUDIT_BEARER_TOKEN_FILE=/protected/path/bearer-token
scripts/full-connectivity-audit.sh
```

The private key and bearer-token files must be mode `0600`; the audit never
prints their values. It writes `artifacts/connectivity-audit.json`, runs signed
route checks inside the deployed container, and proves metrics access through
the real `telnexa.internal.codestra.agency:8443` HTTPS/mTLS edge. It uses unique
synthetic IDs, a reserved phone number, and `.invalid` email addresses. It never
submits to a carrier or email provider. The audit fails closed when the mTLS
identity or bearer-token file is absent.

It validates every control-plane identity and private-gateway route, positive/negative bearer auth, valid/invalid/stale HMAC, replay, idempotency conflict, correlation lookup, Telnexa simulator and DLR read-back, Klyrow test dispatch and callback read-back, metrics, and operator rejection.

Latest: **93 PASS, 0 FAIL** (`20260815T130649Z-c629903b`). Repository suite: **192 tests and 9 subtests PASS**. This proves deployed local paths only; absent workers, credentials, provider accounts, and workflows remain FAIL/BLOCKED.
