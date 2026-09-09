# Corporate call-center runtime hardening change map

This change is source-only. It does not activate email, SMS, PSTN, Odoo writes,
n8n production execution, callbacks, or any external side effect.

## Server placement

- **Server A:** host Caddy, Kong, Keycloak, Middleware/control plane, PostgreSQL,
  Redis, Odoo, n8n main, n8n webhook processors, and n8n queue workers.
- **Server B (`10.40.0.2`):** VICIdial/Asterisk voice execution behind the
  existing private adapter; it never receives browser or n8n traffic.
- **Provider Server (`10.40.0.4`):** Telnexa SMS (`8443`), Klyrow email
  (`18000`), and Kyqra crawler (`3100`). Only Middleware may call these APIs.

The public path is Caddy → Kong → Middleware. n8n is an internal asynchronous
orchestrator and calls only scoped Middleware APIs; it never bypasses Middleware
to reach Odoo, provider services, or databases.

## Strengthened boundaries

| File | Responsibility strengthened |
|---|---|
| `config/call-center-route-contract.yaml` | Canonical route, upstream, scope, issuer, and provider topology contract. |
| `config/integration-registries.yaml` | Exact implemented methods and paths; removes ambiguous reconciliation/admin/session routes. |
| `docs/openapi/control-plane-v1.yaml` | Documents automation callbacks and one-time real-time session creation. |
| `deploy/kong/control-plane.yml` | Enforces scopes for automation and real-time session creation and sends session issuance to the dedicated issuer. |
| `operations/caddy/api.codestra.co.caddy` | Keeps only the WebSocket upgrade on the low-latency direct path; session creation returns to Kong. |
| `migrations/control_plane/006_delivery_leases_and_realtime.sql` | Adds durable leases, fencing tokens, due indexes, and one-time WebSocket nonces. |
| `control_plane_service/leasing.py` | Uses `FOR UPDATE SKIP LOCKED`, pause-aware claims, lease expiry recovery, and worker fencing. |
| `control_plane_service/worker.py` | Consumes owned leases, uses configured timeouts, jittered retries, and cannot complete another worker's lease. |
| `control_plane_service/realtime_gateway.py` | Implements 60-second, tenant/agent/campaign-bound, one-time tokens and a bounded WebSocket listener. |
| `control_plane_service/automation.py` | Converts validation-only n8n events into explicit allowlisted, tenant-scoped, idempotent business-process executions. |
| `deploy/control-plane/compose.realtime.yaml` | Runs the real-time boundary non-root, read-only, secret-file-backed, and host-publishes only the WebSocket port. |
| `deploy/control-plane/Dockerfile` | Pins the WebSocket runtime dependency. |
| `deploy/n8n/compose.queue.yaml` | Adds required digest pinning, queue mode, webhook processor, workers, concurrency, retention, Redis, health, and metrics. |
| `scripts/build_control_plane_workflows.py` | Changes workflows from validation-only to Middleware authorization, durable business-process execution, and completion/failure callbacks. |
| `scripts/validate_n8n_queue_runtime.py` | Rejects mutable n8n tags and incomplete queue/metrics/retention topology before deployment. |
| `config/control-plane.env.example` | Replaces outdated provider addresses with Provider Server `10.40.0.4` endpoints. |
| `tests/test_*leasing.py` | Proves exclusive claims, pause enforcement, lease recovery, and fencing. |
| `tests/test_realtime_gateway.py` | Proves token binding and one-time replay rejection. |
| `tests/test_corporate_call_center_contract.py` | Makes route/provider/n8n topology drift fail CI. |

## Activation gates still required

1. Review and merge through protected branch rules; publish immutable images with SBOM and provenance.
2. Apply migration 006 in staging and rehearse rollback from a fresh encrypted backup.
3. Supply approved secret files; never store their values in Git.
4. Import n8n workflows inactive, bind approved credentials, run synthetic tests, then activate only the approved subset.
5. Certify WebSocket issuer/audience/tenant/agent/campaign claims and replay rejection through Kong and Caddy.
6. Load-test at least two control-plane workers and two n8n workers; prove zero duplicate side effects.
7. Use bounded channel canaries and monitored one-hour and one-business-day soaks before enabling any live-delivery flag.
