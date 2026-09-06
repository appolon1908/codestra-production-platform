from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "contracts/telephony/codestra-calling-api.v1.openapi.yaml"
ECOSYSTEM_PATH = ROOT / "contracts/telephony/codestra-calling-ecosystem.v1.yaml"
ASYNCAPI_PATH = ROOT / "contracts/telephony/codestra-calling-events.v1.asyncapi.yaml"
ENVELOPE_PATH = ROOT / "schemas/integration-event-envelope-v1.schema.json"
DIGEST_PATH = ROOT / "evidence/calling/CALLING-CONTRACT-DIGESTS.json"
REGISTRY_PATH = ROOT / "config/integration-registries.yaml"
WORKFLOW_PATH = ROOT / ".github/workflows/calling-contract.yml"

CONTRACT_FILES = (
    OPENAPI_PATH,
    ECOSYSTEM_PATH,
    ASYNCAPI_PATH,
    ENVELOPE_PATH,
)
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def canonical_digest() -> str:
    lines = []
    for path in CONTRACT_FILES:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(ROOT).as_posix()}\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def endpoint_index(registry: dict) -> dict[tuple[str, str], dict]:
    return {
        (str(item["method"]), str(item["path"])): item
        for item in registry["endpoints"]
    }


def test_contract_digest_is_reproducible_and_fail_closed() -> None:
    evidence = json.loads(DIGEST_PATH.read_text(encoding="utf-8"))
    assert evidence["contract_version"] == "1.0.0"
    assert evidence["digest_algorithm"] == "sha256"
    assert evidence["canonical_digest"] == canonical_digest()
    assert isinstance(evidence["external_effects_enabled"], bool)
    assert evidence["external_effects_enabled"] is False
    assert (
        evidence["authority_issue"]
        == "https://github.com/appolon1908-hue/codestra-production-platform/issues/257"
    )


def test_vicidial_ingress_has_one_route_and_exact_replay_profile() -> None:
    api = load_yaml(OPENAPI_PATH)
    registry = load_yaml(REGISTRY_PATH)
    canonical = "/internal/v1/adapters/vicidial/events"
    operation = api["paths"][canonical]["post"]
    profile = operation["x-codestra-signing-profile"]
    replay = operation["x-codestra-idempotency"]
    constraints = operation["x-codestra-cross-field-constraints"]

    assert operation["requestBody"]["required"] is True
    assert profile["algorithm"] == "HMAC-SHA-256"
    assert profile["canonical_method"] == "POST"
    assert profile["canonical_path"] == canonical
    assert profile["maximum_absolute_clock_skew_seconds"] == 300
    assert profile["signing_input_has_final_lf"] is True
    signing = profile["signing_input"]
    for value in (
        "X-Codestra-Timestamp",
        "POST",
        canonical,
        "Idempotency-Key",
        "payload.event_id",
        "X-Codestra-Content-SHA256",
    ):
        assert value in signing
    assert replay["minimum_retention_seconds"] >= 604800
    assert "original 202" in replay["identical_identity_and_digest"]
    assert "409 IDEMPOTENCY_CONFLICT" in replay[
        "identical_identity_different_digest"
    ]
    assert "envelope.tenant_id == payload.tenant_id" in constraints

    endpoints = endpoint_index(registry)
    assert endpoints[("POST", canonical)]["idempotency_required"] is True
    hooks = [
        item
        for item in registry["webhooks"]
        if item["webhook_id"] == "vicidial-events-v1"
    ]
    assert len(hooks) == 1
    assert hooks[0]["path"] == canonical
    assert hooks[0]["authentication"] == "mtls_hmac_timestamp_v1"
    assert not any(
        path in {"/api/v1/vicidial/events", "/v1/webhooks/vicidial"}
        for _, path in endpoints
    )


def test_odoo_projection_and_readback_are_byte_bound_and_non_enumerating() -> None:
    api = load_yaml(OPENAPI_PATH)
    ecosystem = load_yaml(ECOSYSTEM_PATH)
    registry = load_yaml(REGISTRY_PATH)
    apply_path = "/codestra/api/v1/call-events"
    read_path = "/codestra/api/v1/call-events/{event_id}"
    apply = api["paths"][apply_path]["post"]
    readback = api["paths"][read_path]["get"]

    assert apply["requestBody"]["required"] is True
    assert apply["x-codestra-exposure"] == "private"
    assert readback["x-codestra-exposure"] == "private"
    assert apply["security"] == [{"internalMtls": [], "internalSignature": []}]
    assert readback["security"] == [{"internalMtls": [], "internalSignature": []}]

    apply_signing = apply["x-codestra-signing-profile"]["signing_input"]
    for value in (
        "POST",
        apply_path,
        "X-Codestra-Tenant-ID",
        "X-Codestra-Event-ID",
        "Idempotency-Key",
        "X-Correlation-ID",
        "X-Codestra-Content-SHA256",
    ):
        assert value in apply_signing
    assert (
        apply["x-codestra-idempotency"]["identical_identity_different_digest"]
        .startswith("return 409")
    )
    assert "Idempotency-Key == body.event_id" in apply[
        "x-codestra-cross-field-constraints"
    ]

    read_profile = readback["x-codestra-signing-profile"]
    assert read_profile["canonical_method"] == "GET"
    assert read_profile["request_body_allowed"] is False
    assert read_profile["content_digest"] == "SHA-256 of empty bytes"
    assert EMPTY_SHA256 in read_profile["signing_input"]
    assert (
        readback["x-codestra-authorization"]["cross_tenant_result"]
        == "return the same non-enumerating 404 used for absent events"
    )
    assert "404" in readback["responses"]
    assert "504" in readback["responses"]

    projection = ecosystem["odoo_call_event_projection"]
    assert projection["delivery"]["canonical_path"] == apply_path
    assert projection["delivery"]["tenant_scoped_secret_required"] is True
    assert projection["readback"]["canonical_path_template"] == read_path
    assert projection["readback"]["cross_tenant_result"] == "non_enumerating_404"
    assert projection["readback"]["empty_body_sha256"] == EMPTY_SHA256

    endpoints = endpoint_index(registry)
    assert endpoints[("POST", apply_path)]["system"] == "odoo"
    assert endpoints[("POST", apply_path)]["idempotency_required"] is True
    assert endpoints[("GET", read_path)]["system"] == "odoo"
    connector = next(
        item
        for item in registry["connectors"]
        if item["connector_id"] == "mw-odoo-call-events-v1"
    )
    assert connector["auth_method"] == "mtls_hmac_timestamp_v1"
    assert connector["enabled"] is False


def test_realtime_ticket_and_jetstream_contract_are_complete() -> None:
    api = load_yaml(OPENAPI_PATH)
    ecosystem = load_yaml(ECOSYSTEM_PATH)
    events = load_yaml(ASYNCAPI_PATH)
    registry = load_yaml(REGISTRY_PATH)

    session = api["paths"]["/api/v1/realtime/sessions"]
    assert set(session) == {"post"}
    assert session["post"]["security"] == [{"oidc": ["realtime:session:create"]}]
    assert session["post"]["requestBody"]["required"] is True
    consume = api["paths"]["/internal/v1/realtime/tickets/consume"]["post"]
    assert consume["x-codestra-exposure"] == "private"
    assert consume["security"] == [{"internalMtls": [], "internalBearer": []}]

    transport = ecosystem["realtime"]["event_transport"]
    assert transport["protocol"] == "nats_jetstream"
    assert transport["stream"] == "CODESTRA_CALLING_AGENT_EVENTS"
    assert transport["browser_direct_access"] is False
    assert transport["cursor"] == "jetstream_stream_sequence"
    assert transport["replay_window_seconds"] >= 900
    assert transport["per_connection_queue_messages"] > 0
    assert transport["global_queue_messages"] >= transport[
        "per_connection_queue_messages"
    ]
    assert transport["slow_consumer_close_code"] == 1013

    stream = events["x-codestra-jetstream"]
    assert stream["stream"] == transport["stream"]
    assert stream["storage"] == "file"
    assert stream["replicas"] >= 3
    assert stream["publish_ack_required"] is True
    assert stream["message_id_header"] == "Nats-Msg-Id"
    delivery = events["x-codestra-delivery"]
    assert delivery["cursor"] == "JetStream stream sequence"
    assert delivery["cursor_monotonic"] is True
    assert delivery["per_connection_queue_messages"] == transport[
        "per_connection_queue_messages"
    ]
    assert delivery["global_queue_messages"] == transport["global_queue_messages"]
    assert delivery["slow_consumer_close_code"] == 1013
    authorization = events["x-codestra-authorization"]
    assert authorization["browser_nats_access"] == "forbidden"
    assert authorization["cross_tenant_or_campaign_delivery"] == "forbidden"

    endpoints = endpoint_index(registry)
    assert endpoints[("POST", "/api/v1/realtime/sessions")][
        "required_scope"
    ] == "realtime:session:create"
    assert endpoints[("POST", "/internal/v1/realtime/tickets/consume")][
        "system"
    ] == "middleware"
    assert endpoints[("GET", "/ws/agent")]["system"] == "websocket"
    nats = next(
        item
        for item in registry["protocols"]
        if item["protocol_id"] == "nats-events-v1"
    )
    assert nats["protocol"] == "NATS_JETSTREAM"
    assert nats["stream"] == stream["stream"]
    assert set(nats["approved_callers"]) == {
        "middleware-event-publisher",
        "websocket-event-subscriber",
    }


def test_all_calling_effects_default_false_and_authorities_are_exact() -> None:
    ecosystem = load_yaml(ECOSYSTEM_PATH)
    defaults = ecosystem["activation_defaults"]
    assert defaults
    assert all(isinstance(value, bool) and value is False for value in defaults.values())
    assert ecosystem["authorities"] == {
        "orchestration": "appolon1908-hue/codestra-production-platform",
        "command_boundary": "appolon1908-hue/Middleware-",
        "vicidial_adapter": "appolon1908-hue/Vicidialer-Codestra",
        "realtime_gateway": "appolon1908-hue/Websocket-",
        "agent_workspace": "appolon1908-hue/Odoo",
        "tls_edge": "appolon1908-hue/Caddy",
        "api_policy": "appolon1908-hue/Kong",
        "identity": "appolon1908-hue/Keycloak",
        "generated_clients": "appolon1908-hue/SDK-repository",
        "deployment": "appolon1908-hue/Infustruction-repo",
        "automation": "appolon1908-hue/N8N",
        "operator_ui": "appolon1908-hue/Codestra-Communication-CC",
        "analytics_only": "appolon1908-hue/Superset",
    }


def test_contract_workflow_cannot_skip_or_weaken_itself() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    for required in (
        '".github/workflows/calling-contract.yml"',
        '"contracts/telephony/**"',
        '"schemas/integration-event-envelope-v1.schema.json"',
        '"config/integration-registries.yaml"',
        '"tests/test_calling_contract_digest.py"',
        f"actions/checkout@{CHECKOUT_SHA}",
        "persist-credentials: false",
        "github.event.pull_request.head.sha",
        "tests/test_calling_contract_digest.py",
    ):
        assert required in workflow
    assert "actions/checkout@v" not in workflow
