# Kyqra Connectivity

Validation date: 2026-08-15 UTC

## Deployed middleware adapter

The approved crawler-job adapter was rebuilt and deployed from branch `agent/middleware-n8n-control-plane` to the control-plane API and worker. The deployed API now exposes and successfully executes:

- `POST /v1/crawler/jobs`
- `GET /v1/crawler/jobs/{job_id}`
- `GET /v1/crawler/jobs/{job_id}/results`
- `POST /v1/crawler/jobs/{job_id}/cancel`
- `POST /v1/crawler/jobs/{job_id}/retry`

Safe lifecycle job `5fb4cb66-dabf-4951-a800-34a17d5dfe52` used `https://example.test/kyqra-mission3` and correlation `kyqra-m3-6a778644ac`. Create returned 202, an exact idempotent retry returned the same job with 200, status read-back returned `completed`, result read-back returned one normalized record, cancel returned `cancelled`, retry returned `accepted`, and an invalid operator credential returned 403. No Kyqra Redis or database was accessed.

A signed `kyqra.job.completed` callback returned 202. Odoo delivery completed with zero retries. The pre-existing open n8n circuit produced bounded `CircuitOpen` retries, entered half-open after its 30-second cooldown, delivered on attempt four, and returned to closed. Both downstream targets read back `delivered`; the same correlation ID survived through the event and both delivery records.

## Provider discovery

The only provider endpoint found in existing runtime configuration is `http://10.40.0.2:3100`; the control-plane secret currently contains the unresolved service-DNS contract `http://kyqra:3100`. No local Kyqra, Crawlee, or Playwright service/container exists. The discovered private endpoint on port 3100 and the existing HTTPS Kyqra path both timed out. The `kyqra-deploy@10.40.0.2` SSH endpoint refused the connection. No port was invented or opened.

An inbound Kyqra API/HMAC identity is configured, but it is not evidence of a provider-side outbound service credential. A dedicated outbound credential cannot be registered or verified until the Kyqra API/service owner makes the worker endpoint reachable.

## Status

- Kyqra -> Middleware signed ingress: **PASS**.
- Middleware crawler-job API, lifecycle controls, normalization, retry/circuit recovery, n8n delivery, and Odoo delivery in explicit middleware test mode: **PASS**.
- Middleware -> live Kyqra API -> Kyqra worker: **BLOCKED-EXTERNAL**.
- Overall full worker-backed lifecycle: **BLOCKED-EXTERNAL**.

The live provider leg must not be marked PASS until a reachable Kyqra API executes the job through a real worker, its dedicated service credential rejects an invalid credential, and provider-side status/results/cancel evidence can be read back through that API.
