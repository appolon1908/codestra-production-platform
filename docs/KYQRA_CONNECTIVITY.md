# Kyqra Connectivity

Private `jobs`, `results`, `progress`, and `failures` routes were exercised with safe `example.invalid` payloads. Valid signed events were accepted, exact replays rejected, and duplicate entity classification enforced. Negative bearer/HMAC/freshness tests passed.

Middleware -> Kyqra remains **BLOCKED live**: the deployed control-plane image predates the crawler-job adapter, no Kyqra worker/service endpoint is reachable, and the remote `kyqra-deploy` account is absent. The branch now contains the safe repair—`POST /v1/crawler/jobs`, tenant-scoped read-back, private/test-only targets, fail-closed production authorization, idempotency/correlation persistence, OpenAPI, and passing tests—but source configuration is not live evidence.

Kyqra -> Middleware is PASS for signed synthetic ingress. End-to-end worker execution is BLOCKED pending Kyqra deployment and a safe job API/credential.
