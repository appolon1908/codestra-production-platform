# Middleware/n8n control-plane evidence — 2026-08-15

## Baseline

- Existing private ingress: PASS, `10.40.0.1:8095`, preserved.
- Existing Odoo/n8n containers and workflow exports: PASS, inventoried and unchanged.
- NATS JetStream: PASS, loopback listeners preserved.
- Databases/Redis: PASS, no public listeners.
- Control-plane tests before deployment: PASS, full suite 175 plus 9 subtests.

## Deployment evidence

- API/worker: PASS, Dockerized and restart-managed.
- Bind: PASS, `127.0.0.1:8096` only.
- Safe mode: PASS, outbound delivery false.
- HMAC: PASS valid; invalid returns 401.
- Idempotency: PASS, first 202 and exact retry 200/duplicate.
- Consent: PASS, unsubscribe makes marketing check false.
- RBAC operations summary: PASS.
- Metrics: PASS, queue and circuit gauges.
- Restart persistence: PASS.
- Backup: PASS, checksum valid and `PRAGMA integrity_check=ok`.
- Real SMS/email: NOT_TESTED by policy; none sent.

## Gate

Recommendation: STAGING-ONLY. Odoo/n8n production adapter URLs and credentials require owner approval. Kyqra/Klyrow peer health timed out; Telnexa requires its approved client certificate. Existing production routes continue unchanged.
