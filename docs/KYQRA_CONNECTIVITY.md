# Kyqra Connectivity

Private `jobs`, `results`, `progress`, and `failures` routes were exercised with safe `example.invalid` payloads. Valid signed events were accepted, exact replays rejected, and duplicate entity classification enforced. Negative bearer/HMAC/freshness tests passed.

Middleware -> Kyqra is **FAIL** at the application layer: the deployed control plane has no crawler-job egress method, safe-job runner, provider adapter, or Kyqra URL. Network intent is not a PASS. No local Crawlee/Playwright/Kyqra worker exists, and the remote `kyqra-deploy` account is absent.

Kyqra -> Middleware is PASS for signed synthetic ingress. End-to-end worker execution is BLOCKED pending Kyqra deployment and a safe job API/credential.
