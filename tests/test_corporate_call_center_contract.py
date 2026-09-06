from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_route_contract_is_consistent_across_boundaries():
    registry = text("config/integration-registries.yaml")
    openapi = text("docs/openapi/control-plane-v1.yaml")
    kong = text("deploy/kong/control-plane.yml")
    caddy = text("operations/caddy/api.codestra.co.caddy")
    server = text("control_plane_service/server.py")
    for route in (
        "/api/v1/reconciliation/run", "/api/v1/automation/authorize",
        "/api/v1/automation/execute",
        "/api/v1/automation/results", "/api/v1/realtime/sessions",
    ):
        assert route in registry
        assert route in openapi
        assert route in kong
    for route in ("/api/v1/automation/authorize", "/api/v1/automation/execute",
                  "/api/v1/automation/results"):
        assert route in server
    assert "@realtime path /ws/agent" in caddy
    assert "@realtime path /ws/agent /api/v1/realtime/sessions" not in caddy
    assert "url: http://realtime:18103" in kong
    assert "codestra-control-plane-realtime" not in kong
    assert "auth.codestra.agency" not in registry + openapi + kong + caddy


def test_event_parent_updates_are_fenced_by_the_child_delivery_lease():
    worker = text("control_plane_service/worker.py")
    assert worker.count("if changed == 1:") >= 2
    assert "WHERE event_id=? AND target=? AND lease_owner=? AND lease_token=?" in worker


def test_provider_examples_use_provider_server_and_delivery_stays_off():
    example = text("config/control-plane.env.example")
    assert "TELNEXA_URL=https://telnexa.internal.codestra.agency:8443/v1/messages" in example
    assert "TELNEXA_OUTBOUND_API_KEY_FILE=/run/secrets/telnexa_outbound_api_key" in example
    assert "KLYROW_URL=https://10.40.0.4:18000/v1/email/" in example
    assert "KYQRA_URL=http://10.40.0.4:3100/v1/jobs" in example
    assert "CONTROL_PLANE_OUTBOUND_ENABLED=false" in example
    assert "CONTROL_PLANE_PRODUCTION_DELIVERY_AUTHORIZED=false" in example


def test_n8n_queue_topology_is_pinned_bounded_and_monitored():
    compose = text("deploy/n8n/compose.queue.yaml")
    for required in (
        "EXECUTIONS_MODE: queue", "n8n-webhook:", "n8n-worker:",
        "N8N_WORKER_CONCURRENCY", "N8N_CONCURRENCY_PRODUCTION_LIMIT",
        "EXECUTIONS_DATA_PRUNE", "N8N_METRICS_INCLUDE_QUEUE_METRICS",
        "N8N_WEBHOOK_REPLICAS",
        "N8N_IMAGE must be an approved n8n image pinned with @sha256",
    ):
        assert required in compose
    assert "LIVE_EMAIL_DELIVERY=true" not in compose
    assert "LIVE_SMS_DELIVERY=true" not in compose
