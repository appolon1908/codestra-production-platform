from pathlib import Path

import yaml


def test_migration_chain_has_matching_head_and_rollback() -> None:
    root = Path(__file__).with_name("migrations")
    assert (root / "0001_realtime_gateway.up.sql").is_file()
    assert (root / "0001_realtime_gateway.down.sql").is_file()
    source = Path(__file__).with_name("app.py").read_text(encoding="utf-8")
    assert 'DATABASE_MIGRATION_HEAD = "0001_realtime_gateway"' in source
    assert "CREATE TABLE IF NOT EXISTS realtime_sessions" not in source


def test_gateway_is_published_only_on_canonical_loopback_port() -> None:
    compose = yaml.safe_load(Path(__file__).with_name("compose.yaml").read_text())
    assert compose["services"]["gateway"]["ports"] == ["127.0.0.1:18102:8080"]


def test_open_socket_rechecks_persisted_session_expiry() -> None:
    source = Path(__file__).with_name("app.py").read_text()
    assert "remaining = (scope[\"expires_at\"] - now()).total_seconds()" in source
    assert "await session_is_active(websocket.app.state.pool, scope)" in source
    assert "session_expired_or_revoked" in source


def test_open_socket_revalidates_middleware_authorization_fail_closed() -> None:
    source = Path(__file__).with_name("app.py").read_text()
    assert "/internal/v1/realtime/authorizations/revalidate" in source
    assert "connection.delivery_allowed.clear()" in source
    assert 'code = 1008 if authorization == "denied" else 1011' in source
    assert 'next_revalidation = time.monotonic() + 30.0' in source
    assert "middleware_client()" in source
    compose = Path(__file__).with_name("compose.yaml").read_text()
    for secret in ("middleware_mtls_ca", "middleware_mtls_cert", "middleware_mtls_key"):
        assert secret in compose


def test_socket_consumes_canonical_middleware_ticket() -> None:
    source = Path(__file__).with_name("app.py").read_text()
    assert "/internal/v1/realtime/tickets/consume" in source
    assert "await consume_middleware_ticket(" in source
    assert 'json={"ticket": ticket}' in source


def test_replay_is_watermarked_paginated_and_serialized_with_publication() -> None:
    source = Path(__file__).with_name("app.py").read_text()
    assert "delivery_lock = asyncio.Lock()" in source
    assert source.count("async with delivery_lock:") == 2
    assert "ordinal<=$2" in source
    assert "ORDER BY ordinal LIMIT 1000" in source
    assert "while after < watermark:" in source
    assert source.index("connections[sid] = connection") < source.index("while after < watermark:")


def test_partial_ticket_claim_is_released_even_before_establishment() -> None:
    source = Path(__file__).with_name("app.py").read_text()
    assert "established = False" in source
    assert 'if scope and not scope.get("duplicate"):' in source
    assert "if established and removed:" in source


def test_session_schema_persists_revalidation_authority() -> None:
    migration = (Path(__file__).with_name("migrations") / "0001_realtime_gateway.up.sql").read_text()
    assert "realtime_role text NOT NULL" in migration
    assert "authorization_epoch bigint NOT NULL" in migration


def test_release_publication_serializes_by_version() -> None:
    workflow = (Path(__file__).parents[1] / ".github/workflows/websocket-6101-release.yml").read_text()
    assert "inputs.release_version || github.ref" in workflow


def test_certifier_uses_issued_token_subject() -> None:
    source = Path(__file__).with_name("certify.py").read_text()
    assert 'access_token.split(".")[1]' in source
    assert "user=token_subject" in source
    assert "2a725359-2b9d-42da-af45-9af008a61353" not in source
    keycloak = Path(__file__).with_name("configure_keycloak_certifier.sh").read_text()
    assert "add_mapper authorization_epoch" in keycloak


def test_seeded_sessions_include_required_authorization_fields() -> None:
    source = Path(__file__).with_name("certify.py").read_text()
    assert "realtime_role,authorization_epoch" in source
    assert "'telephony_agent',1" in source


def test_version_endpoint_reports_release_and_contract_identity() -> None:
    source = Path(__file__).with_name("app.py").read_text()
    assert '@app.get("/version")' in source
    for field in ("source_sha", "image_digest", "contract_digest"):
        assert f'"{field}"' in source


def test_recovery_pass_requires_exact_single_render_per_event() -> None:
    source = Path(__file__).with_name("recovery_certify.mjs").read_text()
    assertion = source.index("await deliveries.count() !== 1")
    result = source.index('REPLAY_EXACTLY_ONCE:"PASS"')
    assert assertion < result
