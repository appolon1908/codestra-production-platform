# Server 65 public TLS read-only probe

Date: 2026-09-03
Endpoint: `api.breero.com:443`
Method: TLS handshake only; no HTTP credentials or mutation.

- Protocol: TLS 1.3
- Cipher: `TLS_AES_128_GCM_SHA256`
- Certificate CN: `api.breero.com`
- Signature: ECDSA/SHA-256
- Verification: OK
- Ephemeral key: X25519

TLS handshake and certificate verification pass. This does not certify Caddy
routing, application health/readiness, mTLS policy on private routes, or edge
secret redaction.

TLS=PASS
CADDY=FAIL
SSH_CHANGED=NO
PRODUCTION_CHANGED=NO
CALLS_PLACED=0
